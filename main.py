from dotenv import load_dotenv
load_dotenv()

from src.app import App


def main():
    App().run()


if __name__ == "__main__":
    main()
