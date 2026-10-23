from .config import Settings
from .server import create_server

settings = Settings()
create_server(settings).run(
    transport="http",
    host="0.0.0.0",
    port=settings.port,
    stateless_http=True,
    json_response=True,
    show_banner=False,
)
