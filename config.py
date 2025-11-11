from pydantic import BaseSettings

class Settings(BaseSettings):
    app_name: str = "Noise Info Toolkit"
    debug: bool = False
    
    class Config:
        env_file = ".env"