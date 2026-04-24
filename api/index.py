import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangum import Mangum
from refactored_router.main import app as fastapi_app

handler = Mangum(fastapi_app)
app = fastapi_app
