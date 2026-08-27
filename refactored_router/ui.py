import asyncio
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich import box
from .settings import config
from .stats import stats_service, provider_stats_service
from .rotation import rotation_service
from .schema import CallRecord

class Dashboard:
    def __init__(self):
        self.console = Console()
        # auto_refresh=False: 我们手动控制刷新
        # vertical_overflow="visible": 允许表格被挤到底部
        self.live = Live(self.console, auto_refresh=False, vertical_overflow="visible")
        self.running = False

    def start(self):
        self.running = True
        self.live.start()
        # 初始显示
        self.live.update(self._generate_table(), refresh=True)
        asyncio.create_task(self._updater())

    def stop(self):
        self.running = False
        self.live.stop()

    def _print(self, renderable):
        """核心修改：直接向 Live 的 console 打印，这会显示在表格上方"""
        if self.running:
            self.live.console.print(renderable)
        else:
            self.console.print(renderable)

    def log_request(self, model_id: str, is_stream: bool):
        self._print(f"\n[bold magenta]📨 Request[/bold magenta]: {model_id} (Stream: {is_stream})")

    def log_attempt(self, model_name: str):
        self._print(f"👉 Trying: [cyan]{model_name}[/cyan]...")

    def log_result(self, record: CallRecord, svc=None, show_limit: bool = True):
        # 默认走老路由的 stats_service（network.py 冻结不改动）；
        # 新链路显式传入 provider_stats_service 并关闭 calls/limit 显示（提供商没有每日 limit 概念）
        svc = svc or stats_service
        snapshot = svc.get_snapshot()
        limits = snapshot['limits']
        stats_data = snapshot['stats']

        calls = stats_data.get(record.model_name, {}).get('calls', 0)

        if record.success:
            status = "[bold green]SUCCESS[/bold green]"
            msg = f"Time: {record.response_time:.2f}s"
        else:
            status = "[bold red]FAILED [/bold red]"
            msg = f"[red]{record.error_message}[/red]"

        if show_limit:
            limit = limits.get(record.model_name, 50)
            usage = f"Use: [bold yellow]{calls}/{limit}[/bold yellow]"
        else:
            usage = f"Use: [bold yellow]{calls}[/bold yellow]"

        self._print(
            f"  ↳ {status} [cyan]{record.model_name}[/cyan] | "
            f"{usage} | {msg}"
        )
        # 结果产生时顺便刷新一下表格
        self.refresh()

    def log_error(self, msg: str):
        self._print(f"[bold red]❌ {msg}[/bold red]")

    def refresh(self):
        """只更新表格"""
        if self.running:
            self.live.update(self._generate_table(), refresh=True)

    async def _updater(self):
        while self.running:
            self.refresh()
            await asyncio.sleep(0.5)

    def _generate_table(self) -> Table:
        rstate = rotation_service.get_state()
        table = Table(
            title="🤖 Multi-Provider Router",
            box=box.ROUNDED,
            caption=(
                f"Port: {config.PORT} | Status: Running | "
                f"Rotation: {rstate['current'] or '-'} ({rstate['used']}/{rstate['quota']})"
            ),
            expand=True,
            border_style="bright_black"
        )
        table.add_column("Provider / Model", style="cyan", no_wrap=True)
        table.add_column("Usage", justify="center")
        table.add_column("Success Rate", justify="center")
        table.add_column("Status", justify="center")

        # ---- 多提供商（新路由） ----
        psnap = provider_stats_service.get_snapshot()
        for p in config.PROVIDERS:
            name = p['name']
            st = psnap['stats'].get(name, {})
            calls = st.get('calls', 0)
            success = st.get('success_calls', 0)
            quota = p.get('quota', config.ROTATION_QUOTA)

            usage = str(calls)
            if rstate['current'] == name:
                usage = f"[bold]{calls}[/bold] ({rstate['used']}/{quota}↻)"

            rate = (success / calls * 100) if calls > 0 else 0

            if st.get('is_limited', False):
                status = "🔴 LIMITED"
                status_style = "bold red"
            elif provider_stats_service.is_circuit_open(name):
                status = "🟠 BREAK"
                status_style = "bold yellow"
            elif rstate['current'] == name:
                status = "🟢 Serving"
                status_style = "bold green"
            else:
                status = "🟢 Active"
                status_style = "green"

            table.add_row(name, usage, f"{rate:.1f}%", f"[{status_style}]{status}[/{status_style}]")

        # ---- 老路由（/old 保留） ----
        snapshot = stats_service.get_snapshot()
        stats_data = snapshot['stats']
        limits = snapshot['limits']

        for model in config.MODELS:
            name = model['name']
            st = stats_data.get(name, {})
            calls = st.get('calls', 0)
            success = st.get('success_calls', 0)
            limit = limits.get(name, 50)
            is_limited = st.get('is_limited', False)

            if calls >= limit:
                usage_style = "red"
            elif calls >= limit * 0.8:
                usage_style = "yellow"
            else:
                usage_style = "green"

            rate = (success / calls * 100) if calls > 0 else 0

            if is_limited:
                status = "🔴 LIMITED"
                status_style = "bold red"
            else:
                status = "🟢 Active"
                status_style = "green"

            table.add_row(
                f"[dim][old][/dim] {name}",
                f"[{usage_style}]{calls}/{limit}[/{usage_style}]",
                f"{rate:.1f}%",
                f"[{status_style}]{status}[/{status_style}]"
            )
        return table

# 全局 UI 实例
dashboard = Dashboard()
