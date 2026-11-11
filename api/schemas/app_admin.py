"""
Application Admin Schemas — Pydantic DTOs for Application CRUD.
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class ApplicationDTO(BaseModel):
    """Application response DTO."""
    app_id: int = Field(..., alias="appId")
    app_uuid: str = Field(..., alias="appUuid")
    name: str
    description: Optional[str] = Field("", alias="description")
    app_type: str = Field("internal", alias="appType")
    llm_model: Optional[str] = Field(None, alias="llmModel")
    llm_profile_id: Optional[int] = Field(None, alias="llmProfileId")
    max_tokens_day: int = Field(0, alias="maxTokensDay")
    max_documents: int = Field(0, alias="maxDocuments")
    is_active: Optional[bool] = Field(True, alias="isActive")
    created_by: Optional[int] = Field(None, alias="createdBy")
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    doc_count: int = Field(0, alias="docCount")
    bot_count: int = Field(0, alias="botCount")
    cron_count: int = Field(0, alias="cronCount")

    class Config:
        populate_by_name = True
        from_attributes = True


class ApplicationCreateRequest(BaseModel):
    """Request to create an application."""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    app_type: str = Field("internal", alias="appType")
    llm_model: Optional[str] = Field(None, alias="llmModel")
    max_tokens_day: int = Field(0, alias="maxTokensDay")
    max_documents: int = Field(0, alias="maxDocuments")

    class Config:
        populate_by_name = True


class ApplicationUpdateRequest(BaseModel):
    """Request to update an application."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    app_type: Optional[str] = Field(None, alias="appType")
    llm_model: Optional[str] = Field(None, alias="llmModel")
    llm_profile_id: Optional[int] = Field(None, alias="llmProfileId")
    max_tokens_day: Optional[int] = Field(None, alias="maxTokensDay")
    max_documents: Optional[int] = Field(None, alias="maxDocuments")
    is_active: Optional[bool] = Field(None, alias="isActive")

    class Config:
        populate_by_name = True


class PersonaDTO(BaseModel):
    """Agent Persona response DTO."""
    persona_id: int = Field(..., alias="personaId")
    app_id: int = Field(..., alias="appId")
    name: str
    description: Optional[str] = Field("", alias="description")
    identity_prompt: Optional[str] = Field(None, alias="identityPrompt")
    constraints_prompt: Optional[str] = Field(None, alias="constraintsPrompt")
    communication_prompt: Optional[str] = Field(None, alias="communicationPrompt")
    allowed_tools: Optional[List[str]] = Field(default_factory=list, alias="allowedTools")
    disable_passivity_correction: Optional[bool] = Field(True, alias="disablePassivityCorrection")
    is_default: Optional[bool] = Field(False, alias="isDefault")
    is_active: Optional[bool] = Field(True, alias="isActive")
    input_guardrail_prompt: Optional[str] = Field(None, alias="inputGuardrailPrompt")
    execution_policies: Optional[dict] = Field(default_factory=dict, alias="executionPolicies")
    output_dlp_patterns: Optional[list] = Field(default_factory=list, alias="outputDlpPatterns")
    output_semantic_rules: Optional[str] = Field(None, alias="outputSemanticRules")
    scope_policy: Optional[dict] = Field(default_factory=dict, alias="scopePolicy")
    approval_mode: Optional[str] = Field(None, alias="approvalMode")
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    app_name: Optional[str] = Field(None, alias="appName")

    class Config:
        populate_by_name = True
        from_attributes = True


class PersonaCreateRequest(BaseModel):
    """Request to create an Agent Persona."""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    identity_prompt: str = Field(..., alias="identityPrompt")
    constraints_prompt: str = Field(..., alias="constraintsPrompt")
    communication_prompt: str = Field(..., alias="communicationPrompt")
    allowed_tools: List[str] = Field(..., alias="allowedTools")
    disable_passivity_correction: bool = Field(True, alias="disablePassivityCorrection")
    is_default: bool = Field(False, alias="isDefault")
    input_guardrail_prompt: Optional[str] = Field(None, alias="inputGuardrailPrompt")
    execution_policies: Optional[dict] = Field(None, alias="executionPolicies")
    output_dlp_patterns: Optional[list] = Field(None, alias="outputDlpPatterns")
    output_semantic_rules: Optional[str] = Field(None, alias="outputSemanticRules")
    scope_policy: Optional[dict] = Field(None, alias="scopePolicy")
    approval_mode: Optional[str] = Field(
        None, alias="approvalMode", pattern="^(off|irreversible)?$")

    class Config:
        populate_by_name = True


class PersonaUpdateRequest(BaseModel):
    """Request to update an Agent Persona."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    identity_prompt: Optional[str] = Field(None, alias="identityPrompt")
    constraints_prompt: Optional[str] = Field(None, alias="constraintsPrompt")
    communication_prompt: Optional[str] = Field(None, alias="communicationPrompt")
    allowed_tools: Optional[List[str]] = Field(None, alias="allowedTools")
    disable_passivity_correction: Optional[bool] = Field(None, alias="disablePassivityCorrection")
    is_default: Optional[bool] = Field(None, alias="isDefault")
    is_active: Optional[bool] = Field(None, alias="isActive")
    input_guardrail_prompt: Optional[str] = Field(None, alias="inputGuardrailPrompt")
    execution_policies: Optional[dict] = Field(None, alias="executionPolicies")
    output_dlp_patterns: Optional[list] = Field(None, alias="outputDlpPatterns")
    output_semantic_rules: Optional[str] = Field(None, alias="outputSemanticRules")
    scope_policy: Optional[dict] = Field(None, alias="scopePolicy")
    approval_mode: Optional[str] = Field(
        None, alias="approvalMode", pattern="^(off|irreversible)?$")

    class Config:
        populate_by_name = True
