from src.server.server import RouteGenieServer
from src.utils.logger import logger


class App:
    def __init__(self) -> None:
        logger.info("Initializing Route Genie")
        self.server = RouteGenieServer()

    def run(self) -> None:
        self.server.run()
