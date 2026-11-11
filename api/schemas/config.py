"""
Configuration Schemas
"""
from pydantic import BaseModel, Field
from typing import Optional

class JiraConfig(BaseModel):
    server_url: Optional[str] = Field(None, alias="serverUrl")
    email: Optional[str] = Field(None)
    api_token: Optional[str] = Field(None, alias="apiToken")
    
    class Config:
        populate_by_name = True

class SmtpConfig(BaseModel):
    server: Optional[str] = Field(None)
    port: Optional[int] = Field(None)
    username: Optional[str] = Field(None)
    password: Optional[str] = Field(None)
    use_tls: bool = Field(True, alias="useTls")
    
    class Config:
        populate_by_name = True

class M365Config(BaseModel):
    tenant_id: Optional[str] = Field(None, alias="tenantId")
    client_id: Optional[str] = Field(None, alias="clientId")
    client_secret: Optional[str] = Field(None, alias="clientSecret")
    user_email: Optional[str] = Field(None, alias="userEmail")
    
    class Config:
        populate_by_name = True

class IntegrationsResponse(BaseModel):
    jira: Optional[JiraConfig] = None
    smtp: Optional[SmtpConfig] = None
    m365: Optional[M365Config] = None
