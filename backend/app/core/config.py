from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Cots"
    API_V1_STR: str = "/api/v1"
    
    # 必填项：如果没有在 .env 或环境变量中配置，应用启动会直接报错
    OPENAI_API_KEY: str
    
    # 选填项：从 .env 读取，如果没有则使用默认值
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    MODEL_NAME: str = "gpt-4-turbo-preview"
    
    # 告诉 pydantic 从 .env 文件读取配置（兼容 Pydantic V2）
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()