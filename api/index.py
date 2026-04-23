from mangum import Mangum
from ..refactored_router.main import app as fastapi_app

handler = Mangum(fastapi_app)
