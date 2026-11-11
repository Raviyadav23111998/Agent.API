--
-- Storeglance Agent tenant BOOTSTRAP (no creds, no tenant data)
-- Source of truth: golden tenant prod_agent_tenant_2a5fe12b
-- Contents: full ag_* schema (V034) + curated platform-default seed.
-- Excludes: all credentials/secrets, all tenant-private runtime data,
--           *_bak_v029 backup tables, secret/env-specific configs.
-- Regenerate with scripts/dev/gen_bootstrap.sh
--

-- ============================ SCHEMA ============================
--
-- PostgreSQL database dump
--

\restrict sGLf9DcFEdu9suuC6PafGvEM2b59EjIj6QjiBq1dbcL1qOxfNKLYWznq0NKvX5C

-- Dumped from database version 17.7 (Ubuntu 17.7-0ubuntu0.25.04.1)
-- Dumped by pg_dump version 17.7 (Ubuntu 17.7-0ubuntu0.25.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: ag_agents; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_agents;


--
-- Name: ag_api; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_api;


--
-- Name: SCHEMA ag_api; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA ag_api IS 'External API integration catalog — dynamic, spec-derived, governed agent tools.';


--
-- Name: ag_auth; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_auth;


--
-- Name: ag_bot; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_bot;


--
-- Name: ag_brain; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_brain;


--
-- Name: ag_common; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_common;


--
-- Name: ag_cred; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_cred;


--
-- Name: ag_memory; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_memory;


--
-- Name: ag_notification; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_notification;


--
-- Name: ag_system; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ag_system;


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: ag_common; Owner: -
--

CREATE FUNCTION ag_common.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: utc_now(); Type: FUNCTION; Schema: ag_common; Owner: -
--

CREATE FUNCTION ag_common.utc_now() RETURNS timestamp with time zone
    LANGUAGE sql STABLE
    AS $$
    SELECT NOW();
$$;


--
-- Name: cleanup_expired(); Type: FUNCTION; Schema: ag_memory; Owner: -
--

CREATE FUNCTION ag_memory.cleanup_expired() RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    deleted_count INT;
BEGIN
    DELETE FROM ag_memory.memories
    WHERE expires_at IS NOT NULL AND expires_at < NOW();
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;


--
-- Name: update_conversation_timestamp(); Type: FUNCTION; Schema: ag_system; Owner: -
--

CREATE FUNCTION ag_system.update_conversation_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE ag_system.conversations SET updated_at = NOW()
    WHERE conversation_id = NEW.conversation_id;
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: cron_job_outputs; Type: TABLE; Schema: ag_agents; Owner: -
--

CREATE TABLE ag_agents.cron_job_outputs (
    output_id bigint NOT NULL,
    job_id integer NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: cron_job_outputs_output_id_seq; Type: SEQUENCE; Schema: ag_agents; Owner: -
--

CREATE SEQUENCE ag_agents.cron_job_outputs_output_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cron_job_outputs_output_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_agents; Owner: -
--

ALTER SEQUENCE ag_agents.cron_job_outputs_output_id_seq OWNED BY ag_agents.cron_job_outputs.output_id;


--
-- Name: cron_jobs; Type: TABLE; Schema: ag_agents; Owner: -
--

CREATE TABLE ag_agents.cron_jobs (
    job_id integer NOT NULL,
    name character varying(200) NOT NULL,
    prompt text NOT NULL,
    schedule character varying(100) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    last_run_at timestamp with time zone,
    next_run_at timestamp with time zone,
    run_count integer DEFAULT 0,
    last_status character varying(50),
    last_output text,
    created_by integer,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    job_uuid character varying(12),
    schedule_kind character varying(20) DEFAULT 'once'::character varying,
    schedule_json jsonb DEFAULT '{}'::jsonb,
    repeat_times integer,
    repeat_completed integer DEFAULT 0,
    deliver character varying(100) DEFAULT 'local'::character varying,
    origin_json jsonb,
    last_error text,
    state character varying(50) DEFAULT 'scheduled'::character varying,
    app_id integer DEFAULT 1 NOT NULL,
    consecutive_failures integer DEFAULT 0,
    max_failures integer DEFAULT 3
);


--
-- Name: cron_jobs_job_id_seq; Type: SEQUENCE; Schema: ag_agents; Owner: -
--

CREATE SEQUENCE ag_agents.cron_jobs_job_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cron_jobs_job_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_agents; Owner: -
--

ALTER SEQUENCE ag_agents.cron_jobs_job_id_seq OWNED BY ag_agents.cron_jobs.job_id;


--
-- Name: definitions; Type: TABLE; Schema: ag_agents; Owner: -
--

CREATE TABLE ag_agents.definitions (
    agent_id integer NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    system_prompt text DEFAULT ''::text,
    tools jsonb DEFAULT '[]'::jsonb,
    model character varying(200) DEFAULT ''::character varying,
    schedule character varying(100) DEFAULT ''::character varying,
    enabled boolean DEFAULT true NOT NULL,
    workspace_path character varying(500) DEFAULT ''::character varying,
    deliver character varying(200) DEFAULT 'local'::character varying NOT NULL,
    owner_id character varying(200) DEFAULT '__tenant__'::character varying NOT NULL,
    visibility character varying(50) DEFAULT 'global'::character varying NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb,
    last_run_at timestamp with time zone,
    last_status character varying(50) DEFAULT ''::character varying,
    last_error text DEFAULT ''::text,
    run_count integer DEFAULT 0 NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    app_id integer DEFAULT 1 NOT NULL,
    CONSTRAINT chk_agent_visibility CHECK (((visibility)::text = ANY (ARRAY[('global'::character varying)::text, ('private'::character varying)::text])))
);


--
-- Name: definitions_agent_id_seq; Type: SEQUENCE; Schema: ag_agents; Owner: -
--

CREATE SEQUENCE ag_agents.definitions_agent_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: definitions_agent_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_agents; Owner: -
--

ALTER SEQUENCE ag_agents.definitions_agent_id_seq OWNED BY ag_agents.definitions.agent_id;


--
-- Name: delivery_outbox; Type: TABLE; Schema: ag_agents; Owner: -
--

CREATE TABLE ag_agents.delivery_outbox (
    delivery_id bigint NOT NULL,
    platform character varying(40) NOT NULL,
    chat_id text NOT NULL,
    thread_id text,
    content text NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 5 NOT NULL,
    next_retry_at timestamp with time zone DEFAULT now() NOT NULL,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    delivered_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    CONSTRAINT delivery_outbox_status_check CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('processing'::character varying)::text, ('delivered'::character varying)::text, ('dead'::character varying)::text])))
);


--
-- Name: delivery_outbox_delivery_id_seq; Type: SEQUENCE; Schema: ag_agents; Owner: -
--

CREATE SEQUENCE ag_agents.delivery_outbox_delivery_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: delivery_outbox_delivery_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_agents; Owner: -
--

ALTER SEQUENCE ag_agents.delivery_outbox_delivery_id_seq OWNED BY ag_agents.delivery_outbox.delivery_id;


--
-- Name: runs; Type: TABLE; Schema: ag_agents; Owner: -
--

CREATE TABLE ag_agents.runs (
    run_id bigint NOT NULL,
    agent_id integer NOT NULL,
    status character varying(50) DEFAULT 'running'::character varying NOT NULL,
    input_prompt text,
    output_text text,
    error_message text,
    started_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    completed_at timestamp with time zone,
    duration_ms integer,
    token_count integer,
    triggered_by integer,
    CONSTRAINT chk_run_status CHECK (((status)::text = ANY (ARRAY[('running'::character varying)::text, ('ok'::character varying)::text, ('error'::character varying)::text, ('timeout'::character varying)::text, ('cancelled'::character varying)::text])))
);


--
-- Name: runs_run_id_seq; Type: SEQUENCE; Schema: ag_agents; Owner: -
--

CREATE SEQUENCE ag_agents.runs_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: runs_run_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_agents; Owner: -
--

ALTER SEQUENCE ag_agents.runs_run_id_seq OWNED BY ag_agents.runs.run_id;


--
-- Name: integration_grants; Type: TABLE; Schema: ag_api; Owner: -
--

CREATE TABLE ag_api.integration_grants (
    grant_id bigint NOT NULL,
    integration_id bigint NOT NULL,
    scope character varying(10) NOT NULL,
    ref character varying(100) DEFAULT ''::character varying NOT NULL,
    op_filter jsonb,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_grant_owner CHECK (((((scope)::text = 'org'::text) AND ((ref)::text = ''::text)) OR (((scope)::text = ANY ((ARRAY['app'::character varying, 'persona'::character varying])::text[])) AND ((ref)::text <> ''::text)))),
    CONSTRAINT chk_grant_scope CHECK (((scope)::text = ANY ((ARRAY['app'::character varying, 'persona'::character varying, 'org'::character varying])::text[])))
);


--
-- Name: TABLE integration_grants; Type: COMMENT; Schema: ag_api; Owner: -
--

COMMENT ON TABLE ag_api.integration_grants IS 'Binds an integration to apps/personas. Expanded to op tool_names at the persona/embed filter site so the exact-name whitelist keeps working unchanged.';


--
-- Name: integration_grants_grant_id_seq; Type: SEQUENCE; Schema: ag_api; Owner: -
--

CREATE SEQUENCE ag_api.integration_grants_grant_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: integration_grants_grant_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_api; Owner: -
--

ALTER SEQUENCE ag_api.integration_grants_grant_id_seq OWNED BY ag_api.integration_grants.grant_id;


--
-- Name: integrations; Type: TABLE; Schema: ag_api; Owner: -
--

CREATE TABLE ag_api.integrations (
    integration_id bigint NOT NULL,
    slug character varying(50) NOT NULL,
    display_name character varying(200) NOT NULL,
    base_url character varying(500) NOT NULL,
    spec_kind character varying(20) NOT NULL,
    spec_raw jsonb,
    spec_hash character varying(64) NOT NULL,
    auth_provider character varying(50),
    security_scheme character varying(20),
    auth_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    egress_allow jsonb DEFAULT '[]'::jsonb NOT NULL,
    allow_private boolean DEFAULT false NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    auth_type character varying(40),
    default_headers jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT chk_api_kind CHECK (((spec_kind)::text = ANY ((ARRAY['openapi'::character varying, 'swagger'::character varying, 'mcp'::character varying])::text[]))),
    CONSTRAINT chk_api_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: TABLE integrations; Type: COMMENT; Schema: ag_api; Owner: -
--

COMMENT ON TABLE ag_api.integrations IS 'External API catalog. One row per imported spec. Auth joins ag_cred.providers; credentials resolve per-tenant via Connections.resolve.';


--
-- Name: integrations_integration_id_seq; Type: SEQUENCE; Schema: ag_api; Owner: -
--

CREATE SEQUENCE ag_api.integrations_integration_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: integrations_integration_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_api; Owner: -
--

ALTER SEQUENCE ag_api.integrations_integration_id_seq OWNED BY ag_api.integrations.integration_id;


--
-- Name: operations; Type: TABLE; Schema: ag_api; Owner: -
--

CREATE TABLE ag_api.operations (
    operation_pk bigint NOT NULL,
    integration_id bigint NOT NULL,
    operation_id character varying(120) NOT NULL,
    tool_name character varying(160) NOT NULL,
    http_method character varying(10) NOT NULL,
    path_template character varying(500) NOT NULL,
    summary text,
    description text,
    parameters_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    request_map jsonb DEFAULT '{}'::jsonb NOT NULL,
    side_effect character varying(20) DEFAULT 'write'::character varying NOT NULL,
    requires_approval boolean DEFAULT true NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    embed_safe boolean DEFAULT false NOT NULL,
    response_transform jsonb,
    rate_limit jsonb,
    embedding public.vector(768),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_op_side CHECK (((side_effect)::text = ANY ((ARRAY['read'::character varying, 'write'::character varying, 'irreversible'::character varying])::text[])))
);


--
-- Name: TABLE operations; Type: COMMENT; Schema: ag_api; Owner: -
--

COMMENT ON TABLE ag_api.operations IS 'One row per API endpoint. tool_name = {slug}__{operationId}. parameters_schema is a full JSON Schema passed verbatim to the OpenAI function definition.';


--
-- Name: operations_operation_pk_seq; Type: SEQUENCE; Schema: ag_api; Owner: -
--

CREATE SEQUENCE ag_api.operations_operation_pk_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: operations_operation_pk_seq; Type: SEQUENCE OWNED BY; Schema: ag_api; Owner: -
--

ALTER SEQUENCE ag_api.operations_operation_pk_seq OWNED BY ag_api.operations.operation_pk;


--
-- Name: api_keys; Type: TABLE; Schema: ag_auth; Owner: -
--

CREATE TABLE ag_auth.api_keys (
    key_id integer NOT NULL,
    user_id integer NOT NULL,
    key_prefix character varying(10) NOT NULL,
    key_hash character varying(128) NOT NULL,
    name character varying(200) NOT NULL,
    scopes jsonb DEFAULT '["ai_chat", "brain_search"]'::jsonb,
    is_active boolean DEFAULT true NOT NULL,
    last_used_at timestamp with time zone,
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    revoked_at timestamp with time zone
);


--
-- Name: api_keys_key_id_seq; Type: SEQUENCE; Schema: ag_auth; Owner: -
--

CREATE SEQUENCE ag_auth.api_keys_key_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: api_keys_key_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_auth; Owner: -
--

ALTER SEQUENCE ag_auth.api_keys_key_id_seq OWNED BY ag_auth.api_keys.key_id;


--
-- Name: role_permissions; Type: TABLE; Schema: ag_auth; Owner: -
--

CREATE TABLE ag_auth.role_permissions (
    role_id integer NOT NULL,
    module_id integer NOT NULL,
    can_create boolean DEFAULT false,
    can_read boolean DEFAULT false,
    can_update boolean DEFAULT false,
    can_delete boolean DEFAULT false
);


--
-- Name: roles; Type: TABLE; Schema: ag_auth; Owner: -
--

CREATE TABLE ag_auth.roles (
    role_id integer NOT NULL,
    role_key character varying(50) NOT NULL,
    role_name character varying(200) NOT NULL,
    description text,
    is_system boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: user_permission_overrides; Type: TABLE; Schema: ag_auth; Owner: -
--

CREATE TABLE ag_auth.user_permission_overrides (
    override_id integer NOT NULL,
    user_id integer NOT NULL,
    module_id integer NOT NULL,
    can_create boolean,
    can_read boolean,
    can_update boolean,
    can_delete boolean,
    reason text,
    granted_by integer,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    expires_at timestamp with time zone
);


--
-- Name: users; Type: TABLE; Schema: ag_auth; Owner: -
--

CREATE TABLE ag_auth.users (
    user_id integer NOT NULL,
    external_id character varying(200),
    user_code character varying(100),
    email character varying(300),
    mobile character varying(20),
    full_name character varying(300),
    avatar_url character varying(500),
    role_id integer DEFAULT 3 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    is_blocked boolean DEFAULT false NOT NULL,
    password_hash text,
    salt bytea,
    last_login_at timestamp with time zone,
    metadata_json jsonb DEFAULT '{}'::jsonb,
    platform character varying(50) DEFAULT 'web'::character varying,
    share_ingested boolean DEFAULT false NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_by integer,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    app_id integer
);


--
-- Name: modules; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.modules (
    module_id integer NOT NULL,
    module_name character varying(200) NOT NULL,
    module_key character varying(100) NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: effective_permissions; Type: VIEW; Schema: ag_auth; Owner: -
--

CREATE VIEW ag_auth.effective_permissions AS
 SELECT u.user_id,
    u.user_code,
    u.full_name,
    r.role_key,
    m.module_key,
    m.module_name,
    COALESCE(ov.can_create, rp.can_create, false) AS can_create,
    COALESCE(ov.can_read, rp.can_read, false) AS can_read,
    COALESCE(ov.can_update, rp.can_update, false) AS can_update,
    COALESCE(ov.can_delete, rp.can_delete, false) AS can_delete,
        CASE
            WHEN (ov.override_id IS NOT NULL) THEN true
            ELSE false
        END AS is_overridden
   FROM ((((ag_auth.users u
     JOIN ag_auth.roles r ON ((u.role_id = r.role_id)))
     CROSS JOIN ag_system.modules m)
     LEFT JOIN ag_auth.role_permissions rp ON (((rp.role_id = u.role_id) AND (rp.module_id = m.module_id))))
     LEFT JOIN ag_auth.user_permission_overrides ov ON (((ov.user_id = u.user_id) AND (ov.module_id = m.module_id) AND ((ov.expires_at IS NULL) OR (ov.expires_at > now())))))
  WHERE ((u.is_active = true) AND (m.is_active = true));


--
-- Name: memberships; Type: TABLE; Schema: ag_auth; Owner: -
--

CREATE TABLE ag_auth.memberships (
    membership_id integer NOT NULL,
    user_ext_id character varying(200) NOT NULL,
    display_name character varying(300),
    group_ext_id character varying(200) NOT NULL,
    group_name character varying(300),
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: memberships_membership_id_seq; Type: SEQUENCE; Schema: ag_auth; Owner: -
--

CREATE SEQUENCE ag_auth.memberships_membership_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: memberships_membership_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_auth; Owner: -
--

ALTER SEQUENCE ag_auth.memberships_membership_id_seq OWNED BY ag_auth.memberships.membership_id;


--
-- Name: password_otps; Type: TABLE; Schema: ag_auth; Owner: -
--

CREATE TABLE ag_auth.password_otps (
    otp_id integer NOT NULL,
    user_id integer NOT NULL,
    otp_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used boolean DEFAULT false NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: password_otps_otp_id_seq; Type: SEQUENCE; Schema: ag_auth; Owner: -
--

CREATE SEQUENCE ag_auth.password_otps_otp_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: password_otps_otp_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_auth; Owner: -
--

ALTER SEQUENCE ag_auth.password_otps_otp_id_seq OWNED BY ag_auth.password_otps.otp_id;


--
-- Name: refresh_tokens; Type: TABLE; Schema: ag_auth; Owner: -
--

CREATE TABLE ag_auth.refresh_tokens (
    token_id integer NOT NULL,
    user_id integer NOT NULL,
    token character varying(500) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    session_id character varying(200),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    revoked_at timestamp with time zone
);


--
-- Name: refresh_tokens_token_id_seq; Type: SEQUENCE; Schema: ag_auth; Owner: -
--

CREATE SEQUENCE ag_auth.refresh_tokens_token_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: refresh_tokens_token_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_auth; Owner: -
--

ALTER SEQUENCE ag_auth.refresh_tokens_token_id_seq OWNED BY ag_auth.refresh_tokens.token_id;


--
-- Name: roles_role_id_seq; Type: SEQUENCE; Schema: ag_auth; Owner: -
--

CREATE SEQUENCE ag_auth.roles_role_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_role_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_auth; Owner: -
--

ALTER SEQUENCE ag_auth.roles_role_id_seq OWNED BY ag_auth.roles.role_id;


--
-- Name: user_permission_overrides_override_id_seq; Type: SEQUENCE; Schema: ag_auth; Owner: -
--

CREATE SEQUENCE ag_auth.user_permission_overrides_override_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_permission_overrides_override_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_auth; Owner: -
--

ALTER SEQUENCE ag_auth.user_permission_overrides_override_id_seq OWNED BY ag_auth.user_permission_overrides.override_id;


--
-- Name: user_sessions; Type: TABLE; Schema: ag_auth; Owner: -
--

CREATE TABLE ag_auth.user_sessions (
    session_id character varying(200) NOT NULL,
    user_id integer NOT NULL,
    platform character varying(50),
    agent_type character varying(100),
    ip_address character varying(50),
    login_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    last_active_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    logout_at timestamp with time zone,
    metadata_json jsonb DEFAULT '{}'::jsonb
);


--
-- Name: users_user_id_seq; Type: SEQUENCE; Schema: ag_auth; Owner: -
--

CREATE SEQUENCE ag_auth.users_user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_user_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_auth; Owner: -
--

ALTER SEQUENCE ag_auth.users_user_id_seq OWNED BY ag_auth.users.user_id;


--
-- Name: bot_conversations; Type: TABLE; Schema: ag_bot; Owner: -
--

CREATE TABLE ag_bot.bot_conversations (
    conversation_id uuid DEFAULT gen_random_uuid() NOT NULL,
    bot_id integer NOT NULL,
    session_id character varying(100) NOT NULL,
    page_url text,
    visitor_name character varying(200),
    visitor_email character varying(200),
    message_count integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: bot_messages; Type: TABLE; Schema: ag_bot; Owner: -
--

CREATE TABLE ag_bot.bot_messages (
    message_id bigint NOT NULL,
    conversation_id uuid NOT NULL,
    role character varying(20) NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    token_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    CONSTRAINT chk_bot_msg_role CHECK (((role)::text = ANY (ARRAY[('user'::character varying)::text, ('assistant'::character varying)::text, ('system'::character varying)::text])))
);


--
-- Name: bot_messages_message_id_seq; Type: SEQUENCE; Schema: ag_bot; Owner: -
--

CREATE SEQUENCE ag_bot.bot_messages_message_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bot_messages_message_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_bot; Owner: -
--

ALTER SEQUENCE ag_bot.bot_messages_message_id_seq OWNED BY ag_bot.bot_messages.message_id;


--
-- Name: bot_rules; Type: TABLE; Schema: ag_bot; Owner: -
--

CREATE TABLE ag_bot.bot_rules (
    rule_id integer NOT NULL,
    bot_id integer NOT NULL,
    rule_type character varying(50) DEFAULT 'url_contains'::character varying NOT NULL,
    pattern character varying(500) NOT NULL,
    instruction text NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    CONSTRAINT chk_rule_type CHECK (((rule_type)::text = ANY (ARRAY[('url_contains'::character varying)::text, ('url_exact'::character varying)::text, ('url_regex'::character varying)::text, ('fallback'::character varying)::text])))
);


--
-- Name: bot_rules_rule_id_seq; Type: SEQUENCE; Schema: ag_bot; Owner: -
--

CREATE SEQUENCE ag_bot.bot_rules_rule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bot_rules_rule_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_bot; Owner: -
--

ALTER SEQUENCE ag_bot.bot_rules_rule_id_seq OWNED BY ag_bot.bot_rules.rule_id;


--
-- Name: bots; Type: TABLE; Schema: ag_bot; Owner: -
--

CREATE TABLE ag_bot.bots (
    bot_id integer NOT NULL,
    bot_uuid uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(200) NOT NULL,
    description text DEFAULT ''::text,
    api_token character varying(64) NOT NULL,
    allowed_domains text[] DEFAULT '{*}'::text[],
    system_prompt text DEFAULT 'You are a helpful assistant.'::text NOT NULL,
    welcome_message text DEFAULT 'Hi! How can I help you today?'::text,
    model character varying(100),
    theme_color character varying(7) DEFAULT '#6D28D9'::character varying,
    max_context_docs integer DEFAULT 5,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    app_id integer,
    api_token_hash character varying(64),
    persona_id integer,
    mode text DEFAULT 'chat'::text NOT NULL,
    publishable_key text,
    secret_key_enc text,
    guardrail_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    rate_limits jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT bots_mode_chk CHECK ((mode = ANY (ARRAY['chat'::text, 'copilot'::text])))
);


--
-- Name: bots_bot_id_seq; Type: SEQUENCE; Schema: ag_bot; Owner: -
--

CREATE SEQUENCE ag_bot.bots_bot_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bots_bot_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_bot; Owner: -
--

ALTER SEQUENCE ag_bot.bots_bot_id_seq OWNED BY ag_bot.bots.bot_id;


--
-- Name: embed_action_audit; Type: TABLE; Schema: ag_bot; Owner: -
--

CREATE TABLE ag_bot.embed_action_audit (
    id bigint NOT NULL,
    integration_id integer NOT NULL,
    session_id text NOT NULL,
    tool_name text NOT NULL,
    target_label text,
    tool_args text,
    result text,
    status text NOT NULL,
    client_ip text,
    end_user_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: embed_action_audit_id_seq; Type: SEQUENCE; Schema: ag_bot; Owner: -
--

CREATE SEQUENCE ag_bot.embed_action_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: embed_action_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_bot; Owner: -
--

ALTER SEQUENCE ag_bot.embed_action_audit_id_seq OWNED BY ag_bot.embed_action_audit.id;


--
-- Name: answer_cache; Type: TABLE; Schema: ag_brain; Owner: -
--

CREATE TABLE ag_brain.answer_cache (
    question_hash character varying(64) NOT NULL,
    question_text text NOT NULL,
    question_keywords text NOT NULL,
    answer text NOT NULL,
    bundle_name character varying(200) DEFAULT ''::character varying,
    model character varying(200) DEFAULT ''::character varying,
    input_tokens_saved integer DEFAULT 0,
    hit_count integer DEFAULT 0,
    last_hit_at timestamp with time zone,
    ttl_seconds integer DEFAULT 7200,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: content_cache; Type: TABLE; Schema: ag_brain; Owner: -
--

CREATE TABLE ag_brain.content_cache (
    cache_id bigint NOT NULL,
    source_uri character varying(1000) NOT NULL,
    owner_id character varying(200) DEFAULT '__tenant__'::character varying NOT NULL,
    content text NOT NULL,
    content_hash character varying(64) NOT NULL,
    fetched_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    ttl_seconds integer DEFAULT 3600 NOT NULL,
    source_type character varying(100) DEFAULT ''::character varying,
    size_bytes bigint DEFAULT 0,
    app_id integer DEFAULT 1 NOT NULL
);


--
-- Name: content_cache_cache_id_seq; Type: SEQUENCE; Schema: ag_brain; Owner: -
--

CREATE SEQUENCE ag_brain.content_cache_cache_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: content_cache_cache_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_brain; Owner: -
--

ALTER SEQUENCE ag_brain.content_cache_cache_id_seq OWNED BY ag_brain.content_cache.cache_id;


--
-- Name: context_bundles; Type: TABLE; Schema: ag_brain; Owner: -
--

CREATE TABLE ag_brain.context_bundles (
    bundle_id bigint NOT NULL,
    name character varying(300) NOT NULL,
    description text,
    max_tokens integer DEFAULT 1000000 NOT NULL,
    total_tokens integer DEFAULT 0 NOT NULL,
    document_count integer DEFAULT 0 NOT NULL,
    doc_ids jsonb DEFAULT '[]'::jsonb,
    cached_payload text,
    payload_built_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: context_bundles_bundle_id_seq; Type: SEQUENCE; Schema: ag_brain; Owner: -
--

CREATE SEQUENCE ag_brain.context_bundles_bundle_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: context_bundles_bundle_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_brain; Owner: -
--

ALTER SEQUENCE ag_brain.context_bundles_bundle_id_seq OWNED BY ag_brain.context_bundles.bundle_id;


--
-- Name: document_chunks; Type: TABLE; Schema: ag_brain; Owner: -
--

CREATE TABLE ag_brain.document_chunks (
    chunk_id bigint NOT NULL,
    doc_id bigint NOT NULL,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    token_count integer DEFAULT 0 NOT NULL,
    embedding public.vector(768),
    embedding_model character varying(100),
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: document_chunks_chunk_id_seq; Type: SEQUENCE; Schema: ag_brain; Owner: -
--

CREATE SEQUENCE ag_brain.document_chunks_chunk_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_chunks_chunk_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_brain; Owner: -
--

ALTER SEQUENCE ag_brain.document_chunks_chunk_id_seq OWNED BY ag_brain.document_chunks.chunk_id;


--
-- Name: document_index_state; Type: TABLE; Schema: ag_brain; Owner: -
--

CREATE TABLE ag_brain.document_index_state (
    doc_id bigint NOT NULL,
    pillar text NOT NULL,
    state text DEFAULT 'pending'::text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    last_error text,
    next_retry_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: documents; Type: TABLE; Schema: ag_brain; Owner: -
--

CREATE TABLE ag_brain.documents (
    doc_id bigint NOT NULL,
    source_path character varying(1000) NOT NULL,
    doc_type character varying(50) DEFAULT 'document'::character varying NOT NULL,
    title character varying(500) DEFAULT ''::character varying,
    content text NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb,
    content_hash character varying(64) NOT NULL,
    token_count integer DEFAULT 0,
    status character varying(50) DEFAULT 'pending'::character varying NOT NULL,
    owner_id character varying(200) DEFAULT '__tenant__'::character varying NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    fts_vector tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, (((COALESCE(title, ''::character varying))::text || ' '::text) || COALESCE(content, ''::text)))) STORED,
    tags text[] DEFAULT '{}'::text[],
    app_id integer DEFAULT 1 NOT NULL,
    embedding public.vector(768),
    embedding_model character varying(100),
    CONSTRAINT chk_doc_status CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('indexed'::character varying)::text, ('error'::character varying)::text, ('archived'::character varying)::text])))
);


--
-- Name: documents_doc_id_seq; Type: SEQUENCE; Schema: ag_brain; Owner: -
--

CREATE SEQUENCE ag_brain.documents_doc_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: documents_doc_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_brain; Owner: -
--

ALTER SEQUENCE ag_brain.documents_doc_id_seq OWNED BY ag_brain.documents.doc_id;


--
-- Name: entities; Type: TABLE; Schema: ag_brain; Owner: -
--

CREATE TABLE ag_brain.entities (
    entity_id bigint NOT NULL,
    name character varying(500) NOT NULL,
    entity_type character varying(100) NOT NULL,
    owner_id character varying(200) DEFAULT '__tenant__'::character varying NOT NULL,
    source_uri character varying(1000) DEFAULT ''::character varying,
    properties_json jsonb DEFAULT '{}'::jsonb,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    fts_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, (((COALESCE(name, ''::character varying))::text || ' '::text) || (COALESCE(entity_type, ''::character varying))::text))) STORED,
    app_id integer DEFAULT 1 NOT NULL
);


--
-- Name: entities_entity_id_seq; Type: SEQUENCE; Schema: ag_brain; Owner: -
--

CREATE SEQUENCE ag_brain.entities_entity_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: entities_entity_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_brain; Owner: -
--

ALTER SEQUENCE ag_brain.entities_entity_id_seq OWNED BY ag_brain.entities.entity_id;


--
-- Name: ingestion_log; Type: TABLE; Schema: ag_brain; Owner: -
--

CREATE TABLE ag_brain.ingestion_log (
    log_id bigint NOT NULL,
    doc_id bigint NOT NULL,
    action character varying(100) NOT NULL,
    details text DEFAULT ''::text,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: ingestion_log_log_id_seq; Type: SEQUENCE; Schema: ag_brain; Owner: -
--

CREATE SEQUENCE ag_brain.ingestion_log_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ingestion_log_log_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_brain; Owner: -
--

ALTER SEQUENCE ag_brain.ingestion_log_log_id_seq OWNED BY ag_brain.ingestion_log.log_id;


--
-- Name: relations; Type: TABLE; Schema: ag_brain; Owner: -
--

CREATE TABLE ag_brain.relations (
    relation_id bigint NOT NULL,
    from_entity_id bigint NOT NULL,
    to_entity_id bigint NOT NULL,
    relation_type character varying(100) NOT NULL,
    source_uri character varying(1000) DEFAULT ''::character varying,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: relations_relation_id_seq; Type: SEQUENCE; Schema: ag_brain; Owner: -
--

CREATE SEQUENCE ag_brain.relations_relation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: relations_relation_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_brain; Owner: -
--

ALTER SEQUENCE ag_brain.relations_relation_id_seq OWNED BY ag_brain.relations.relation_id;


--
-- Name: sync_state; Type: TABLE; Schema: ag_brain; Owner: -
--

CREATE TABLE ag_brain.sync_state (
    source_key character varying(100) NOT NULL,
    last_sync_at timestamp with time zone,
    sync_cursor text,
    docs_synced integer DEFAULT 0,
    status character varying(50) DEFAULT 'idle'::character varying NOT NULL,
    error_message text,
    config_json jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    app_id integer DEFAULT 1 NOT NULL,
    CONSTRAINT chk_sync_status CHECK (((status)::text = ANY (ARRAY[('idle'::character varying)::text, ('running'::character varying)::text, ('error'::character varying)::text, ('paused'::character varying)::text])))
);


--
-- Name: connections; Type: TABLE; Schema: ag_cred; Owner: -
--

CREATE TABLE ag_cred.connections (
    connection_id bigint NOT NULL,
    provider_key character varying(50) NOT NULL,
    scope character varying(10) NOT NULL,
    owner_ref character varying(100) DEFAULT ''::character varying NOT NULL,
    label character varying(200) DEFAULT 'Default'::character varying NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    secret_enc text,
    status character varying(20) DEFAULT 'unverified'::character varying NOT NULL,
    last_verified_at timestamp with time zone,
    last_used_at timestamp with time zone,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_conn_owner CHECK (((((scope)::text = 'org'::text) AND ((owner_ref)::text = ''::text)) OR (((scope)::text = ANY ((ARRAY['user'::character varying, 'app'::character varying])::text[])) AND ((owner_ref)::text <> ''::text)))),
    CONSTRAINT chk_conn_scope CHECK (((scope)::text = ANY ((ARRAY['org'::character varying, 'user'::character varying, 'app'::character varying])::text[]))),
    CONSTRAINT chk_conn_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'unverified'::character varying, 'error'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: TABLE connections; Type: COMMENT; Schema: ag_cred; Owner: -
--

COMMENT ON TABLE ag_cred.connections IS 'One row per (provider, scope, owner). No separate bindings table — the row is the binding.';


--
-- Name: connections_connection_id_seq; Type: SEQUENCE; Schema: ag_cred; Owner: -
--

CREATE SEQUENCE ag_cred.connections_connection_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: connections_connection_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_cred; Owner: -
--

ALTER SEQUENCE ag_cred.connections_connection_id_seq OWNED BY ag_cred.connections.connection_id;


--
-- Name: providers; Type: TABLE; Schema: ag_cred; Owner: -
--

CREATE TABLE ag_cred.providers (
    provider_key character varying(50) NOT NULL,
    display_name character varying(200) NOT NULL,
    category character varying(50) DEFAULT 'integration'::character varying NOT NULL,
    kind character varying(20) DEFAULT 'direct'::character varying NOT NULL,
    fields jsonb DEFAULT '[]'::jsonb NOT NULL,
    supports_user boolean DEFAULT true NOT NULL,
    supports_verify boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 100 NOT NULL,
    icon_url character varying(500),
    docs_url character varying(500),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_provider_kind CHECK (((kind)::text = ANY ((ARRAY['direct'::character varying, 'shared_app'::character varying])::text[])))
);


--
-- Name: TABLE providers; Type: COMMENT; Schema: ag_cred; Owner: -
--

COMMENT ON TABLE ag_cred.providers IS 'Credential provider registry. kind drives resolution: direct = self-contained, shared_app = org app registration merged with per-principal identity.';


--
-- Name: entities; Type: TABLE; Schema: ag_memory; Owner: -
--

CREATE TABLE ag_memory.entities (
    entity_id bigint NOT NULL,
    name character varying(500) NOT NULL,
    entity_type character varying(100) NOT NULL,
    user_id character varying(200) DEFAULT '__tenant__'::character varying NOT NULL,
    properties jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: entities_entity_id_seq; Type: SEQUENCE; Schema: ag_memory; Owner: -
--

CREATE SEQUENCE ag_memory.entities_entity_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: entities_entity_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_memory; Owner: -
--

ALTER SEQUENCE ag_memory.entities_entity_id_seq OWNED BY ag_memory.entities.entity_id;


--
-- Name: memories; Type: TABLE; Schema: ag_memory; Owner: -
--

CREATE TABLE ag_memory.memories (
    memory_id bigint NOT NULL,
    user_id character varying(200) DEFAULT '__tenant__'::character varying NOT NULL,
    layer character varying(50) DEFAULT 'semantic'::character varying NOT NULL,
    category character varying(100) DEFAULT 'fact'::character varying NOT NULL,
    key character varying(500) NOT NULL,
    value text NOT NULL,
    confidence real DEFAULT 1.0 NOT NULL,
    source character varying(200) DEFAULT ''::character varying NOT NULL,
    access_count integer DEFAULT 0 NOT NULL,
    last_accessed timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    fts_vector tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, (((COALESCE(key, ''::character varying))::text || ' '::text) || COALESCE(value, ''::text)))) STORED,
    app_id integer DEFAULT 1 NOT NULL,
    CONSTRAINT chk_memory_layer CHECK (((layer)::text = ANY (ARRAY[('session'::character varying)::text, ('episodic'::character varying)::text, ('semantic'::character varying)::text, ('company'::character varying)::text])))
);


--
-- Name: memories_memory_id_seq; Type: SEQUENCE; Schema: ag_memory; Owner: -
--

CREATE SEQUENCE ag_memory.memories_memory_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: memories_memory_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_memory; Owner: -
--

ALTER SEQUENCE ag_memory.memories_memory_id_seq OWNED BY ag_memory.memories.memory_id;


--
-- Name: memory_tags; Type: TABLE; Schema: ag_memory; Owner: -
--

CREATE TABLE ag_memory.memory_tags (
    memory_id bigint NOT NULL,
    tag character varying(100) NOT NULL
);


--
-- Name: relations; Type: TABLE; Schema: ag_memory; Owner: -
--

CREATE TABLE ag_memory.relations (
    source_id bigint NOT NULL,
    target_id bigint NOT NULL,
    relation_type character varying(100) NOT NULL,
    properties jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: email_notifications; Type: TABLE; Schema: ag_notification; Owner: -
--

CREATE TABLE ag_notification.email_notifications (
    email_template_id integer NOT NULL,
    type character varying(100),
    subject character varying(100),
    body text,
    data_fields text,
    created_by integer NOT NULL,
    creation_date timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by integer,
    updation_date timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: email_notifications_email_template_id_seq; Type: SEQUENCE; Schema: ag_notification; Owner: -
--

ALTER TABLE ag_notification.email_notifications ALTER COLUMN email_template_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ag_notification.email_notifications_email_template_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notification_recipients; Type: TABLE; Schema: ag_notification; Owner: -
--

CREATE TABLE ag_notification.notification_recipients (
    recipient_id bigint NOT NULL,
    notification_id integer NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    read_at timestamp with time zone
);


--
-- Name: notification_recipients_recipient_id_seq; Type: SEQUENCE; Schema: ag_notification; Owner: -
--

ALTER TABLE ag_notification.notification_recipients ALTER COLUMN recipient_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME ag_notification.notification_recipients_recipient_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notifications; Type: TABLE; Schema: ag_notification; Owner: -
--

CREATE TABLE ag_notification.notifications (
    notification_id integer NOT NULL,
    template_id integer,
    sender_id integer NOT NULL,
    target_scope character varying(50) NOT NULL,
    target_reference_id integer,
    final_title character varying(255) NOT NULL,
    final_body text NOT NULL,
    data_payload jsonb,
    status character varying(20) DEFAULT 'pending'::character varying,
    priority smallint DEFAULT 1,
    scheduled_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
    processed_at timestamp with time zone,
    total_recipients integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now())
);


--
-- Name: notifications_notification_id_seq; Type: SEQUENCE; Schema: ag_notification; Owner: -
--

ALTER TABLE ag_notification.notifications ALTER COLUMN notification_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME ag_notification.notifications_notification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: push_notification_template; Type: TABLE; Schema: ag_notification; Owner: -
--

CREATE TABLE ag_notification.push_notification_template (
    push_notification_template_id integer NOT NULL,
    template_type character varying(250) NOT NULL,
    title text NOT NULL,
    template character varying(255),
    fields character varying(255),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
    template_code character varying(100),
    app_route_pattern character varying(255),
    web_route_pattern character varying(255),
    priority_level smallint DEFAULT 1,
    image_url text
);


--
-- Name: push_notification_template_push_notification_template_id_seq; Type: SEQUENCE; Schema: ag_notification; Owner: -
--

ALTER TABLE ag_notification.push_notification_template ALTER COLUMN push_notification_template_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME ag_notification.push_notification_template_push_notification_template_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: push_notification_tokens; Type: TABLE; Schema: ag_notification; Owner: -
--

CREATE TABLE ag_notification.push_notification_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    token text NOT NULL,
    auth_key character varying(255),
    p256dh_key character varying(255),
    platform character varying(50) NOT NULL,
    device_type character varying(50),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
    last_used_at timestamp with time zone,
    expires_at timestamp with time zone,
    updated_at timestamp with time zone,
    device_model character varying(100),
    app_version character varying(20),
    failure_count integer DEFAULT 0,
    last_sync_at timestamp with time zone
);


--
-- Name: push_notification_tokens_id_seq; Type: SEQUENCE; Schema: ag_notification; Owner: -
--

ALTER TABLE ag_notification.push_notification_tokens ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME ag_notification.push_notification_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: push_notifications; Type: TABLE; Schema: ag_notification; Owner: -
--

CREATE TABLE ag_notification.push_notifications (
    push_notification_id integer NOT NULL,
    notification_id integer NOT NULL,
    push_notification_token_id integer NOT NULL,
    title character varying(255),
    data text,
    status character varying(50) DEFAULT 'pending'::character varying,
    error_message text,
    delivered_at timestamp with time zone,
    read_at timestamp with time zone,
    updated_at timestamp with time zone,
    retry_count integer DEFAULT 0,
    campaign_id integer,
    user_id integer,
    fcm_message_id character varying(255),
    resolved_route character varying(255),
    clicked_at timestamp with time zone,
    click_count integer DEFAULT 0
);


--
-- Name: push_notifications_push_notification_id_seq; Type: SEQUENCE; Schema: ag_notification; Owner: -
--

ALTER TABLE ag_notification.push_notifications ALTER COLUMN push_notification_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME ag_notification.push_notifications_push_notification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: action_audit; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.action_audit (
    audit_id bigint NOT NULL,
    user_id integer,
    conversation_id text,
    tool_name text NOT NULL,
    side_effect text NOT NULL,
    args_summary text,
    approved boolean,
    status text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE action_audit; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON TABLE ag_system.action_audit IS 'Audit trail of side-effecting agent tool executions (V013).';


--
-- Name: action_audit_audit_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.action_audit_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: action_audit_audit_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.action_audit_audit_id_seq OWNED BY ag_system.action_audit.audit_id;


--
-- Name: address; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.address (
    address_id integer NOT NULL,
    address_type character varying(20) NOT NULL,
    associated_to character varying(50) NOT NULL,
    associated_id integer NOT NULL,
    address_line1 character varying(150) NOT NULL,
    address_line2 character varying(50),
    suburb character varying(100),
    postcode character varying(10),
    state_id smallint,
    country_id smallint,
    geo_location character varying(70),
    created_by integer,
    creation_date timestamp with time zone DEFAULT timezone('utc'::text, now()),
    updated_by integer,
    updation_date timestamp with time zone
);


--
-- Name: address_address_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

ALTER TABLE ag_system.address ALTER COLUMN address_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME ag_system.address_address_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: agent_personas; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.agent_personas (
    persona_id integer NOT NULL,
    app_id integer NOT NULL,
    name character varying(200) NOT NULL,
    description text DEFAULT ''::text,
    identity_prompt text NOT NULL,
    constraints_prompt text NOT NULL,
    communication_prompt text DEFAULT 'Be concise, friendly, and professional. Use markdown formatting.'::text NOT NULL,
    allowed_tools jsonb NOT NULL,
    disable_passivity_correction boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    input_guardrail_prompt text,
    execution_policies jsonb DEFAULT '{}'::jsonb,
    output_dlp_patterns jsonb DEFAULT '[]'::jsonb,
    output_semantic_rules text,
    approval_mode character varying(20) DEFAULT NULL::character varying,
    CONSTRAINT agent_personas_approval_mode_check CHECK (((approval_mode IS NULL) OR ((approval_mode)::text = ANY (ARRAY[('off'::character varying)::text, ('irreversible'::character varying)::text]))))
);


--
-- Name: COLUMN agent_personas.input_guardrail_prompt; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.agent_personas.input_guardrail_prompt IS 'Hard security boundary injected into the LLM system prompt. E.g. "Only discuss order tracking."';


--
-- Name: COLUMN agent_personas.execution_policies; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.agent_personas.execution_policies IS 'IAM-style JSON rules. Blacklist model: tools NOT listed are allowed. Example: {"jira_update_ticket": {"status": {"$not_in": ["Closed"]}}}';


--
-- Name: COLUMN agent_personas.output_dlp_patterns; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.agent_personas.output_dlp_patterns IS 'Regex patterns for deterministic DLP redaction. Example: ["SCRUM-\\d+", "(?i)password\\s*[:=]\\s*\\S+"]';


--
-- Name: COLUMN agent_personas.output_semantic_rules; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.agent_personas.output_semantic_rules IS 'Natural-language rules for LLM-based output filtering. Example: "Never reveal internal IP addresses or server names."';


--
-- Name: COLUMN agent_personas.approval_mode; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.agent_personas.approval_mode IS 'HITL approval gate: ''irreversible'' = ask user before irreversible tools, ''off'' = never ask, NULL = inherit global config';


--
-- Name: agent_personas_persona_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.agent_personas_persona_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_personas_persona_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.agent_personas_persona_id_seq OWNED BY ag_system.agent_personas.persona_id;


--
-- Name: applications; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.applications (
    app_id integer NOT NULL,
    app_uuid uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(200) NOT NULL,
    description text DEFAULT ''::text,
    app_type character varying(50) DEFAULT 'internal'::character varying NOT NULL,
    llm_model character varying(200),
    llm_api_key_enc text,
    max_tokens_day integer DEFAULT 0,
    max_documents integer DEFAULT 0,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    CONSTRAINT chk_app_type CHECK (((app_type)::text = ANY (ARRAY[('internal'::character varying)::text, ('chatbot'::character varying)::text, ('api'::character varying)::text, ('mobile'::character varying)::text, ('widget'::character varying)::text])))
);


--
-- Name: applications_app_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.applications_app_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: applications_app_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.applications_app_id_seq OWNED BY ag_system.applications.app_id;


--
-- Name: artifacts; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.artifacts (
    artifact_id bigint NOT NULL,
    name character varying(300) NOT NULL,
    title character varying(500),
    content text NOT NULL,
    session_id character varying(200),
    user_id character varying(200),
    request_feedback boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: artifacts_artifact_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.artifacts_artifact_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: artifacts_artifact_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.artifacts_artifact_id_seq OWNED BY ag_system.artifacts.artifact_id;


--
-- Name: audit_log; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.audit_log (
    log_id bigint NOT NULL,
    action character varying(100) NOT NULL,
    entity_type character varying(100),
    entity_id character varying(200),
    user_id integer,
    details_json jsonb DEFAULT '{}'::jsonb,
    ip_address character varying(50),
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: audit_log_log_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.audit_log_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_log_log_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.audit_log_log_id_seq OWNED BY ag_system.audit_log.log_id;


--
-- Name: checkpoints; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.checkpoints (
    checkpoint_id bigint NOT NULL,
    session_id character varying(200) NOT NULL,
    user_id character varying(200),
    iteration integer NOT NULL,
    checkpoint_data jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: checkpoints_checkpoint_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.checkpoints_checkpoint_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: checkpoints_checkpoint_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.checkpoints_checkpoint_id_seq OWNED BY ag_system.checkpoints.checkpoint_id;


--
-- Name: code_types; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.code_types (
    code_type_id smallint NOT NULL,
    name character varying(25) NOT NULL,
    description character varying(200),
    created_by integer,
    creation_date timestamp with time zone DEFAULT timezone('utc'::text, now()),
    updated_by integer,
    updation_date timestamp with time zone
);


--
-- Name: code_types_code_type_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

ALTER TABLE ag_system.code_types ALTER COLUMN code_type_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME ag_system.code_types_code_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: codes; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.codes (
    code_id smallint NOT NULL,
    code_type_id smallint,
    parent_id smallint,
    code character varying(200) NOT NULL,
    weightage integer,
    value character varying(200),
    english_name character varying(200),
    hindi_name character varying(200),
    created_by integer,
    creation_date timestamp with time zone DEFAULT timezone('utc'::text, now()),
    updated_by integer,
    updation_date timestamp with time zone
);


--
-- Name: codes_code_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

ALTER TABLE ag_system.codes ALTER COLUMN code_id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME ag_system.codes_code_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: configs; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.configs (
    config_id integer NOT NULL,
    config_key character varying(200) NOT NULL,
    config_value text,
    description text,
    is_secret boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    config_type character varying(20) DEFAULT 'text'::character varying,
    config_group character varying(50) DEFAULT ''::character varying,
    sort_order integer DEFAULT 100,
    requires_restart boolean DEFAULT false
);


--
-- Name: COLUMN configs.config_type; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.configs.config_type IS 'UI input type: text, number, boolean, password, select, textarea';


--
-- Name: COLUMN configs.config_group; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.configs.config_group IS 'Logical group prefix (llm, agent, brain, memory, auth, secret, smtp, etc.)';


--
-- Name: COLUMN configs.requires_restart; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.configs.requires_restart IS 'If TRUE, changes to this key need a process restart to take effect';


--
-- Name: configs_config_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.configs_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: configs_config_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.configs_config_id_seq OWNED BY ag_system.configs.config_id;


--
-- Name: conversation_summaries; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.conversation_summaries (
    summary_id bigint NOT NULL,
    user_id integer,
    session_id character varying(200),
    summary text NOT NULL,
    message_count integer,
    started_at timestamp with time zone,
    ended_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: conversation_summaries_summary_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.conversation_summaries_summary_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: conversation_summaries_summary_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.conversation_summaries_summary_id_seq OWNED BY ag_system.conversation_summaries.summary_id;


--
-- Name: conversations; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.conversations (
    conversation_id text NOT NULL,
    user_id integer NOT NULL,
    title text DEFAULT ''::text,
    agent_id integer,
    model text DEFAULT ''::text,
    message_count integer DEFAULT 0,
    is_archived boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    source character varying(20) DEFAULT 'web'::character varying NOT NULL,
    processing_until timestamp with time zone
);


--
-- Name: COLUMN conversations.processing_until; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.conversations.processing_until IS 'Active-processing claim: worker holds the conversation until this time. NULL/past = free.';


--
-- Name: credential_bindings; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.credential_bindings (
    binding_id bigint NOT NULL,
    context_type character varying(20) NOT NULL,
    context_id character varying(100) NOT NULL,
    provider_key character varying(50) NOT NULL,
    credential_id bigint NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    CONSTRAINT chk_binding_context CHECK (((context_type)::text = ANY (ARRAY[('system'::character varying)::text, ('user'::character varying)::text, ('app'::character varying)::text])))
);


--
-- Name: TABLE credential_bindings; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON TABLE ag_system.credential_bindings IS 'IAM-style bindings linking contexts (user/app/system) to vault credentials.';


--
-- Name: COLUMN credential_bindings.context_type; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.credential_bindings.context_type IS 'system = global infra, user = personal, app = cron job / automated workflow';


--
-- Name: COLUMN credential_bindings.context_id; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.credential_bindings.context_id IS 'system → __system__, user → user_id as string, app → app_id (e.g. email_triage)';


--
-- Name: credential_bindings_binding_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.credential_bindings_binding_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credential_bindings_binding_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.credential_bindings_binding_id_seq OWNED BY ag_system.credential_bindings.binding_id;


--
-- Name: credential_providers; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.credential_providers (
    provider_key character varying(50) NOT NULL,
    display_name character varying(200) NOT NULL,
    category character varying(50) DEFAULT 'integration'::character varying NOT NULL,
    config_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    icon_url character varying(500),
    docs_url character varying(500),
    supports_user boolean DEFAULT true NOT NULL,
    supports_verify boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 100 NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    org_app boolean DEFAULT false NOT NULL,
    CONSTRAINT chk_provider_category CHECK (((category)::text = ANY (ARRAY[('infrastructure'::character varying)::text, ('ai_model'::character varying)::text, ('integration'::character varying)::text, ('platform'::character varying)::text])))
);


--
-- Name: TABLE credential_providers; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON TABLE ag_system.credential_providers IS 'Schema registry for external service providers. Drives UI forms and validation.';


--
-- Name: COLUMN credential_providers.config_schema; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.credential_providers.config_schema IS 'JSON schema defining non-secret config fields (server_url, email, port, etc.)';


--
-- Name: COLUMN credential_providers.supports_user; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.credential_providers.supports_user IS 'If TRUE, regular users can create personal credentials for this provider.';


--
-- Name: credential_vault; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.credential_vault (
    credential_id bigint NOT NULL,
    provider_key character varying(50) NOT NULL,
    owner_type character varying(20) DEFAULT 'user'::character varying NOT NULL,
    owner_id integer,
    label character varying(200) DEFAULT 'Default'::character varying NOT NULL,
    config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    secret_enc text,
    is_active boolean DEFAULT true NOT NULL,
    status character varying(30) DEFAULT 'active'::character varying NOT NULL,
    last_verified timestamp with time zone,
    last_used_at timestamp with time zone,
    created_by integer,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    CONSTRAINT chk_vault_owner CHECK (((((owner_type)::text = 'system'::text) AND (owner_id IS NULL)) OR (((owner_type)::text = 'user'::text) AND (owner_id IS NOT NULL)))),
    CONSTRAINT chk_vault_owner_type CHECK (((owner_type)::text = ANY (ARRAY[('system'::character varying)::text, ('user'::character varying)::text]))),
    CONSTRAINT chk_vault_status CHECK (((status)::text = ANY (ARRAY[('active'::character varying)::text, ('error'::character varying)::text, ('expired'::character varying)::text, ('revoked'::character varying)::text, ('unverified'::character varying)::text])))
);


--
-- Name: TABLE credential_vault; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON TABLE ag_system.credential_vault IS 'Encrypted credential storage. Each row = one stored credential. Users can have multiple per provider.';


--
-- Name: COLUMN credential_vault.label; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.credential_vault.label IS 'Human-readable label so users can distinguish multiple creds for the same provider.';


--
-- Name: COLUMN credential_vault.secret_enc; Type: COMMENT; Schema: ag_system; Owner: -
--

COMMENT ON COLUMN ag_system.credential_vault.secret_enc IS 'Fernet-encrypted secret value (api_token, password, client_secret). Decrypted at runtime by CredentialRegistry.';


--
-- Name: credential_vault_credential_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.credential_vault_credential_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credential_vault_credential_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.credential_vault_credential_id_seq OWNED BY ag_system.credential_vault.credential_id;


--
-- Name: files; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.files (
    file_id bigint NOT NULL,
    file_type character varying(50) NOT NULL,
    associated_to character varying(100) NOT NULL,
    associated_id bigint,
    file_path character varying(1000) NOT NULL,
    file_name character varying(300),
    extension character varying(20),
    size_bytes bigint,
    mime_type character varying(100),
    created_by integer,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: files_file_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.files_file_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: files_file_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.files_file_id_seq OWNED BY ag_system.files.file_id;


--
-- Name: integrations; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.integrations (
    integration_id integer NOT NULL,
    service_key character varying(100) NOT NULL,
    display_name character varying(200),
    is_enabled boolean DEFAULT false NOT NULL,
    config_json jsonb DEFAULT '{}'::jsonb,
    credentials_enc text,
    last_verified timestamp with time zone,
    status character varying(50) DEFAULT 'unconfigured'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    updated_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    CONSTRAINT chk_integration_status CHECK (((status)::text = ANY (ARRAY[('unconfigured'::character varying)::text, ('active'::character varying)::text, ('error'::character varying)::text, ('expired'::character varying)::text, ('revoked'::character varying)::text])))
);


--
-- Name: integrations_integration_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.integrations_integration_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: integrations_integration_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.integrations_integration_id_seq OWNED BY ag_system.integrations.integration_id;


--
-- Name: messages; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.messages (
    message_id integer NOT NULL,
    conversation_id text NOT NULL,
    role text NOT NULL,
    content text DEFAULT ''::text,
    tool_calls jsonb DEFAULT '[]'::jsonb,
    tool_call_id text,
    token_count integer DEFAULT 0,
    metadata_json jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: messages_message_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.messages_message_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: messages_message_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.messages_message_id_seq OWNED BY ag_system.messages.message_id;


--
-- Name: migration_history; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.migration_history (
    migration_id integer NOT NULL,
    version character varying(50) NOT NULL,
    script_name character varying(200) NOT NULL,
    description text,
    checksum character varying(64),
    applied_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL,
    applied_by character varying(100) DEFAULT 'system'::character varying,
    execution_ms integer
);


--
-- Name: migration_history_migration_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.migration_history_migration_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: migration_history_migration_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.migration_history_migration_id_seq OWNED BY ag_system.migration_history.migration_id;


--
-- Name: modules_module_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.modules_module_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: modules_module_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.modules_module_id_seq OWNED BY ag_system.modules.module_id;


--
-- Name: processed_emails; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.processed_emails (
    message_id character varying(255) NOT NULL,
    processed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    queue_id character varying(50) DEFAULT 'default'::character varying NOT NULL
);


--
-- Name: tenant_stats; Type: VIEW; Schema: ag_system; Owner: -
--

CREATE VIEW ag_system.tenant_stats AS
 SELECT ( SELECT count(*) AS count
           FROM ag_auth.users
          WHERE (users.is_active = true)) AS active_users,
    ( SELECT count(*) AS count
           FROM ag_brain.documents) AS total_documents,
    ( SELECT count(*) AS count
           FROM ag_brain.documents
          WHERE ((documents.status)::text = 'indexed'::text)) AS indexed_documents,
    ( SELECT count(*) AS count
           FROM ag_memory.memories) AS total_memories,
    ( SELECT count(*) AS count
           FROM ag_brain.entities) AS brain_entities,
    ( SELECT count(*) AS count
           FROM ag_brain.relations) AS brain_relations,
    ( SELECT count(*) AS count
           FROM ag_memory.entities) AS memory_entities,
    ( SELECT count(*) AS count
           FROM ag_agents.definitions
          WHERE (definitions.enabled = true)) AS active_agents,
    ( SELECT count(*) AS count
           FROM ag_agents.runs
          WHERE (runs.started_at > (now() - '24:00:00'::interval))) AS runs_24h,
    ( SELECT count(*) AS count
           FROM ag_system.audit_log
          WHERE (audit_log.created_at > (now() - '24:00:00'::interval))) AS audit_24h,
    ( SELECT pg_size_pretty(pg_database_size(current_database())) AS pg_size_pretty) AS db_size;


--
-- Name: transcript_logs; Type: TABLE; Schema: ag_system; Owner: -
--

CREATE TABLE ag_system.transcript_logs (
    log_id bigint NOT NULL,
    session_id character varying(200) NOT NULL,
    user_id character varying(200),
    step_index integer DEFAULT 0 NOT NULL,
    source character varying(50) NOT NULL,
    step_type character varying(100) NOT NULL,
    content text,
    tool_calls jsonb,
    created_at timestamp with time zone DEFAULT ag_common.utc_now() NOT NULL
);


--
-- Name: transcript_logs_log_id_seq; Type: SEQUENCE; Schema: ag_system; Owner: -
--

CREATE SEQUENCE ag_system.transcript_logs_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: transcript_logs_log_id_seq; Type: SEQUENCE OWNED BY; Schema: ag_system; Owner: -
--

ALTER SEQUENCE ag_system.transcript_logs_log_id_seq OWNED BY ag_system.transcript_logs.log_id;


--
-- Name: cron_job_outputs output_id; Type: DEFAULT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.cron_job_outputs ALTER COLUMN output_id SET DEFAULT nextval('ag_agents.cron_job_outputs_output_id_seq'::regclass);


--
-- Name: cron_jobs job_id; Type: DEFAULT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.cron_jobs ALTER COLUMN job_id SET DEFAULT nextval('ag_agents.cron_jobs_job_id_seq'::regclass);


--
-- Name: definitions agent_id; Type: DEFAULT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.definitions ALTER COLUMN agent_id SET DEFAULT nextval('ag_agents.definitions_agent_id_seq'::regclass);


--
-- Name: delivery_outbox delivery_id; Type: DEFAULT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.delivery_outbox ALTER COLUMN delivery_id SET DEFAULT nextval('ag_agents.delivery_outbox_delivery_id_seq'::regclass);


--
-- Name: runs run_id; Type: DEFAULT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.runs ALTER COLUMN run_id SET DEFAULT nextval('ag_agents.runs_run_id_seq'::regclass);


--
-- Name: integration_grants grant_id; Type: DEFAULT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.integration_grants ALTER COLUMN grant_id SET DEFAULT nextval('ag_api.integration_grants_grant_id_seq'::regclass);


--
-- Name: integrations integration_id; Type: DEFAULT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.integrations ALTER COLUMN integration_id SET DEFAULT nextval('ag_api.integrations_integration_id_seq'::regclass);


--
-- Name: operations operation_pk; Type: DEFAULT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.operations ALTER COLUMN operation_pk SET DEFAULT nextval('ag_api.operations_operation_pk_seq'::regclass);


--
-- Name: api_keys key_id; Type: DEFAULT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.api_keys ALTER COLUMN key_id SET DEFAULT nextval('ag_auth.api_keys_key_id_seq'::regclass);


--
-- Name: memberships membership_id; Type: DEFAULT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.memberships ALTER COLUMN membership_id SET DEFAULT nextval('ag_auth.memberships_membership_id_seq'::regclass);


--
-- Name: password_otps otp_id; Type: DEFAULT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.password_otps ALTER COLUMN otp_id SET DEFAULT nextval('ag_auth.password_otps_otp_id_seq'::regclass);


--
-- Name: refresh_tokens token_id; Type: DEFAULT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.refresh_tokens ALTER COLUMN token_id SET DEFAULT nextval('ag_auth.refresh_tokens_token_id_seq'::regclass);


--
-- Name: roles role_id; Type: DEFAULT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.roles ALTER COLUMN role_id SET DEFAULT nextval('ag_auth.roles_role_id_seq'::regclass);


--
-- Name: user_permission_overrides override_id; Type: DEFAULT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.user_permission_overrides ALTER COLUMN override_id SET DEFAULT nextval('ag_auth.user_permission_overrides_override_id_seq'::regclass);


--
-- Name: users user_id; Type: DEFAULT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.users ALTER COLUMN user_id SET DEFAULT nextval('ag_auth.users_user_id_seq'::regclass);


--
-- Name: bot_messages message_id; Type: DEFAULT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bot_messages ALTER COLUMN message_id SET DEFAULT nextval('ag_bot.bot_messages_message_id_seq'::regclass);


--
-- Name: bot_rules rule_id; Type: DEFAULT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bot_rules ALTER COLUMN rule_id SET DEFAULT nextval('ag_bot.bot_rules_rule_id_seq'::regclass);


--
-- Name: bots bot_id; Type: DEFAULT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bots ALTER COLUMN bot_id SET DEFAULT nextval('ag_bot.bots_bot_id_seq'::regclass);


--
-- Name: embed_action_audit id; Type: DEFAULT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.embed_action_audit ALTER COLUMN id SET DEFAULT nextval('ag_bot.embed_action_audit_id_seq'::regclass);


--
-- Name: content_cache cache_id; Type: DEFAULT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.content_cache ALTER COLUMN cache_id SET DEFAULT nextval('ag_brain.content_cache_cache_id_seq'::regclass);


--
-- Name: context_bundles bundle_id; Type: DEFAULT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.context_bundles ALTER COLUMN bundle_id SET DEFAULT nextval('ag_brain.context_bundles_bundle_id_seq'::regclass);


--
-- Name: document_chunks chunk_id; Type: DEFAULT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.document_chunks ALTER COLUMN chunk_id SET DEFAULT nextval('ag_brain.document_chunks_chunk_id_seq'::regclass);


--
-- Name: documents doc_id; Type: DEFAULT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.documents ALTER COLUMN doc_id SET DEFAULT nextval('ag_brain.documents_doc_id_seq'::regclass);


--
-- Name: entities entity_id; Type: DEFAULT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.entities ALTER COLUMN entity_id SET DEFAULT nextval('ag_brain.entities_entity_id_seq'::regclass);


--
-- Name: ingestion_log log_id; Type: DEFAULT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.ingestion_log ALTER COLUMN log_id SET DEFAULT nextval('ag_brain.ingestion_log_log_id_seq'::regclass);


--
-- Name: relations relation_id; Type: DEFAULT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.relations ALTER COLUMN relation_id SET DEFAULT nextval('ag_brain.relations_relation_id_seq'::regclass);


--
-- Name: connections connection_id; Type: DEFAULT; Schema: ag_cred; Owner: -
--

ALTER TABLE ONLY ag_cred.connections ALTER COLUMN connection_id SET DEFAULT nextval('ag_cred.connections_connection_id_seq'::regclass);


--
-- Name: entities entity_id; Type: DEFAULT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.entities ALTER COLUMN entity_id SET DEFAULT nextval('ag_memory.entities_entity_id_seq'::regclass);


--
-- Name: memories memory_id; Type: DEFAULT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.memories ALTER COLUMN memory_id SET DEFAULT nextval('ag_memory.memories_memory_id_seq'::regclass);


--
-- Name: action_audit audit_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.action_audit ALTER COLUMN audit_id SET DEFAULT nextval('ag_system.action_audit_audit_id_seq'::regclass);


--
-- Name: agent_personas persona_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.agent_personas ALTER COLUMN persona_id SET DEFAULT nextval('ag_system.agent_personas_persona_id_seq'::regclass);


--
-- Name: applications app_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.applications ALTER COLUMN app_id SET DEFAULT nextval('ag_system.applications_app_id_seq'::regclass);


--
-- Name: artifacts artifact_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.artifacts ALTER COLUMN artifact_id SET DEFAULT nextval('ag_system.artifacts_artifact_id_seq'::regclass);


--
-- Name: audit_log log_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.audit_log ALTER COLUMN log_id SET DEFAULT nextval('ag_system.audit_log_log_id_seq'::regclass);


--
-- Name: checkpoints checkpoint_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.checkpoints ALTER COLUMN checkpoint_id SET DEFAULT nextval('ag_system.checkpoints_checkpoint_id_seq'::regclass);


--
-- Name: configs config_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.configs ALTER COLUMN config_id SET DEFAULT nextval('ag_system.configs_config_id_seq'::regclass);


--
-- Name: conversation_summaries summary_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.conversation_summaries ALTER COLUMN summary_id SET DEFAULT nextval('ag_system.conversation_summaries_summary_id_seq'::regclass);


--
-- Name: credential_bindings binding_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.credential_bindings ALTER COLUMN binding_id SET DEFAULT nextval('ag_system.credential_bindings_binding_id_seq'::regclass);


--
-- Name: credential_vault credential_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.credential_vault ALTER COLUMN credential_id SET DEFAULT nextval('ag_system.credential_vault_credential_id_seq'::regclass);


--
-- Name: files file_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.files ALTER COLUMN file_id SET DEFAULT nextval('ag_system.files_file_id_seq'::regclass);


--
-- Name: integrations integration_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.integrations ALTER COLUMN integration_id SET DEFAULT nextval('ag_system.integrations_integration_id_seq'::regclass);


--
-- Name: messages message_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.messages ALTER COLUMN message_id SET DEFAULT nextval('ag_system.messages_message_id_seq'::regclass);


--
-- Name: migration_history migration_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.migration_history ALTER COLUMN migration_id SET DEFAULT nextval('ag_system.migration_history_migration_id_seq'::regclass);


--
-- Name: modules module_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.modules ALTER COLUMN module_id SET DEFAULT nextval('ag_system.modules_module_id_seq'::regclass);


--
-- Name: transcript_logs log_id; Type: DEFAULT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.transcript_logs ALTER COLUMN log_id SET DEFAULT nextval('ag_system.transcript_logs_log_id_seq'::regclass);


--
-- Name: cron_job_outputs cron_job_outputs_pkey; Type: CONSTRAINT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.cron_job_outputs
    ADD CONSTRAINT cron_job_outputs_pkey PRIMARY KEY (output_id);


--
-- Name: cron_jobs cron_jobs_pkey; Type: CONSTRAINT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.cron_jobs
    ADD CONSTRAINT cron_jobs_pkey PRIMARY KEY (job_id);


--
-- Name: definitions definitions_name_key; Type: CONSTRAINT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.definitions
    ADD CONSTRAINT definitions_name_key UNIQUE (name);


--
-- Name: definitions definitions_pkey; Type: CONSTRAINT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.definitions
    ADD CONSTRAINT definitions_pkey PRIMARY KEY (agent_id);


--
-- Name: delivery_outbox delivery_outbox_pkey; Type: CONSTRAINT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.delivery_outbox
    ADD CONSTRAINT delivery_outbox_pkey PRIMARY KEY (delivery_id);


--
-- Name: runs runs_pkey; Type: CONSTRAINT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.runs
    ADD CONSTRAINT runs_pkey PRIMARY KEY (run_id);


--
-- Name: integration_grants integration_grants_pkey; Type: CONSTRAINT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.integration_grants
    ADD CONSTRAINT integration_grants_pkey PRIMARY KEY (grant_id);


--
-- Name: integrations integrations_pkey; Type: CONSTRAINT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.integrations
    ADD CONSTRAINT integrations_pkey PRIMARY KEY (integration_id);


--
-- Name: operations operations_pkey; Type: CONSTRAINT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.operations
    ADD CONSTRAINT operations_pkey PRIMARY KEY (operation_pk);


--
-- Name: integrations uq_api_slug; Type: CONSTRAINT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.integrations
    ADD CONSTRAINT uq_api_slug UNIQUE (slug);


--
-- Name: integration_grants uq_grant; Type: CONSTRAINT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.integration_grants
    ADD CONSTRAINT uq_grant UNIQUE (integration_id, scope, ref);


--
-- Name: operations uq_op; Type: CONSTRAINT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.operations
    ADD CONSTRAINT uq_op UNIQUE (integration_id, operation_id);


--
-- Name: api_keys api_keys_key_hash_key; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.api_keys
    ADD CONSTRAINT api_keys_key_hash_key UNIQUE (key_hash);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (key_id);


--
-- Name: memberships memberships_pkey; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.memberships
    ADD CONSTRAINT memberships_pkey PRIMARY KEY (membership_id);


--
-- Name: memberships memberships_user_ext_id_group_ext_id_key; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.memberships
    ADD CONSTRAINT memberships_user_ext_id_group_ext_id_key UNIQUE (user_ext_id, group_ext_id);


--
-- Name: password_otps password_otps_pkey; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.password_otps
    ADD CONSTRAINT password_otps_pkey PRIMARY KEY (otp_id);


--
-- Name: refresh_tokens refresh_tokens_pkey; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.refresh_tokens
    ADD CONSTRAINT refresh_tokens_pkey PRIMARY KEY (token_id);


--
-- Name: refresh_tokens refresh_tokens_token_key; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.refresh_tokens
    ADD CONSTRAINT refresh_tokens_token_key UNIQUE (token);


--
-- Name: role_permissions role_permissions_pkey; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.role_permissions
    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (role_id, module_id);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (role_id);


--
-- Name: roles roles_role_key_key; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.roles
    ADD CONSTRAINT roles_role_key_key UNIQUE (role_key);


--
-- Name: user_permission_overrides user_permission_overrides_pkey; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.user_permission_overrides
    ADD CONSTRAINT user_permission_overrides_pkey PRIMARY KEY (override_id);


--
-- Name: user_permission_overrides user_permission_overrides_user_id_module_id_key; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.user_permission_overrides
    ADD CONSTRAINT user_permission_overrides_user_id_module_id_key UNIQUE (user_id, module_id);


--
-- Name: user_sessions user_sessions_pkey; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.user_sessions
    ADD CONSTRAINT user_sessions_pkey PRIMARY KEY (session_id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (user_id);


--
-- Name: users users_user_code_key; Type: CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.users
    ADD CONSTRAINT users_user_code_key UNIQUE (user_code);


--
-- Name: bot_conversations bot_conversations_pkey; Type: CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bot_conversations
    ADD CONSTRAINT bot_conversations_pkey PRIMARY KEY (conversation_id);


--
-- Name: bot_messages bot_messages_pkey; Type: CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bot_messages
    ADD CONSTRAINT bot_messages_pkey PRIMARY KEY (message_id);


--
-- Name: bot_rules bot_rules_pkey; Type: CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bot_rules
    ADD CONSTRAINT bot_rules_pkey PRIMARY KEY (rule_id);


--
-- Name: bots bots_api_token_key; Type: CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bots
    ADD CONSTRAINT bots_api_token_key UNIQUE (api_token);


--
-- Name: bots bots_bot_uuid_key; Type: CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bots
    ADD CONSTRAINT bots_bot_uuid_key UNIQUE (bot_uuid);


--
-- Name: bots bots_pkey; Type: CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bots
    ADD CONSTRAINT bots_pkey PRIMARY KEY (bot_id);


--
-- Name: embed_action_audit embed_action_audit_pkey; Type: CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.embed_action_audit
    ADD CONSTRAINT embed_action_audit_pkey PRIMARY KEY (id);


--
-- Name: answer_cache answer_cache_pkey; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.answer_cache
    ADD CONSTRAINT answer_cache_pkey PRIMARY KEY (question_hash);


--
-- Name: content_cache content_cache_pkey; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.content_cache
    ADD CONSTRAINT content_cache_pkey PRIMARY KEY (cache_id);


--
-- Name: content_cache content_cache_source_uri_owner_id_key; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.content_cache
    ADD CONSTRAINT content_cache_source_uri_owner_id_key UNIQUE (source_uri, owner_id);


--
-- Name: context_bundles context_bundles_name_key; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.context_bundles
    ADD CONSTRAINT context_bundles_name_key UNIQUE (name);


--
-- Name: context_bundles context_bundles_pkey; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.context_bundles
    ADD CONSTRAINT context_bundles_pkey PRIMARY KEY (bundle_id);


--
-- Name: document_chunks document_chunks_doc_id_chunk_index_key; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.document_chunks
    ADD CONSTRAINT document_chunks_doc_id_chunk_index_key UNIQUE (doc_id, chunk_index);


--
-- Name: document_chunks document_chunks_pkey; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.document_chunks
    ADD CONSTRAINT document_chunks_pkey PRIMARY KEY (chunk_id);


--
-- Name: document_index_state document_index_state_pkey; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.document_index_state
    ADD CONSTRAINT document_index_state_pkey PRIMARY KEY (doc_id, pillar);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (doc_id);


--
-- Name: documents documents_source_path_key; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.documents
    ADD CONSTRAINT documents_source_path_key UNIQUE (source_path);


--
-- Name: entities entities_name_entity_type_owner_id_key; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.entities
    ADD CONSTRAINT entities_name_entity_type_owner_id_key UNIQUE (name, entity_type, owner_id);


--
-- Name: entities entities_pkey; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.entities
    ADD CONSTRAINT entities_pkey PRIMARY KEY (entity_id);


--
-- Name: ingestion_log ingestion_log_pkey; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.ingestion_log
    ADD CONSTRAINT ingestion_log_pkey PRIMARY KEY (log_id);


--
-- Name: relations relations_from_entity_id_to_entity_id_relation_type_key; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.relations
    ADD CONSTRAINT relations_from_entity_id_to_entity_id_relation_type_key UNIQUE (from_entity_id, to_entity_id, relation_type);


--
-- Name: relations relations_pkey; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.relations
    ADD CONSTRAINT relations_pkey PRIMARY KEY (relation_id);


--
-- Name: sync_state sync_state_pkey; Type: CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.sync_state
    ADD CONSTRAINT sync_state_pkey PRIMARY KEY (source_key);


--
-- Name: connections connections_pkey; Type: CONSTRAINT; Schema: ag_cred; Owner: -
--

ALTER TABLE ONLY ag_cred.connections
    ADD CONSTRAINT connections_pkey PRIMARY KEY (connection_id);


--
-- Name: providers providers_pkey; Type: CONSTRAINT; Schema: ag_cred; Owner: -
--

ALTER TABLE ONLY ag_cred.providers
    ADD CONSTRAINT providers_pkey PRIMARY KEY (provider_key);


--
-- Name: connections uq_conn; Type: CONSTRAINT; Schema: ag_cred; Owner: -
--

ALTER TABLE ONLY ag_cred.connections
    ADD CONSTRAINT uq_conn UNIQUE (provider_key, scope, owner_ref);


--
-- Name: entities entities_name_entity_type_user_id_key; Type: CONSTRAINT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.entities
    ADD CONSTRAINT entities_name_entity_type_user_id_key UNIQUE (name, entity_type, user_id);


--
-- Name: entities entities_pkey; Type: CONSTRAINT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.entities
    ADD CONSTRAINT entities_pkey PRIMARY KEY (entity_id);


--
-- Name: memories memories_pkey; Type: CONSTRAINT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.memories
    ADD CONSTRAINT memories_pkey PRIMARY KEY (memory_id);


--
-- Name: memories memories_user_id_key_key; Type: CONSTRAINT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.memories
    ADD CONSTRAINT memories_user_id_key_key UNIQUE (user_id, key);


--
-- Name: memory_tags memory_tags_pkey; Type: CONSTRAINT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.memory_tags
    ADD CONSTRAINT memory_tags_pkey PRIMARY KEY (memory_id, tag);


--
-- Name: relations relations_pkey; Type: CONSTRAINT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.relations
    ADD CONSTRAINT relations_pkey PRIMARY KEY (source_id, target_id, relation_type);


--
-- Name: email_notifications email_notifications_pkey; Type: CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.email_notifications
    ADD CONSTRAINT email_notifications_pkey PRIMARY KEY (email_template_id);


--
-- Name: notification_recipients notification_recipients_notification_id_user_id_key; Type: CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.notification_recipients
    ADD CONSTRAINT notification_recipients_notification_id_user_id_key UNIQUE (notification_id, user_id);


--
-- Name: notification_recipients notification_recipients_pkey; Type: CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.notification_recipients
    ADD CONSTRAINT notification_recipients_pkey PRIMARY KEY (recipient_id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (notification_id);


--
-- Name: push_notification_template push_notification_template_pkey; Type: CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.push_notification_template
    ADD CONSTRAINT push_notification_template_pkey PRIMARY KEY (push_notification_template_id);


--
-- Name: push_notification_template push_notification_template_template_code_key; Type: CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.push_notification_template
    ADD CONSTRAINT push_notification_template_template_code_key UNIQUE (template_code);


--
-- Name: push_notification_tokens push_notification_tokens_pkey; Type: CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.push_notification_tokens
    ADD CONSTRAINT push_notification_tokens_pkey PRIMARY KEY (id);


--
-- Name: push_notification_tokens push_notification_tokens_user_id_token_platform_key; Type: CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.push_notification_tokens
    ADD CONSTRAINT push_notification_tokens_user_id_token_platform_key UNIQUE (user_id, token, platform);


--
-- Name: push_notifications push_notifications_pkey; Type: CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.push_notifications
    ADD CONSTRAINT push_notifications_pkey PRIMARY KEY (push_notification_id);


--
-- Name: action_audit action_audit_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.action_audit
    ADD CONSTRAINT action_audit_pkey PRIMARY KEY (audit_id);


--
-- Name: address address_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.address
    ADD CONSTRAINT address_pkey PRIMARY KEY (address_id);


--
-- Name: agent_personas agent_personas_app_id_name_key; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.agent_personas
    ADD CONSTRAINT agent_personas_app_id_name_key UNIQUE (app_id, name);


--
-- Name: agent_personas agent_personas_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.agent_personas
    ADD CONSTRAINT agent_personas_pkey PRIMARY KEY (persona_id);


--
-- Name: applications applications_app_uuid_key; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.applications
    ADD CONSTRAINT applications_app_uuid_key UNIQUE (app_uuid);


--
-- Name: applications applications_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.applications
    ADD CONSTRAINT applications_pkey PRIMARY KEY (app_id);


--
-- Name: artifacts artifacts_name_session_id_key; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.artifacts
    ADD CONSTRAINT artifacts_name_session_id_key UNIQUE (name, session_id);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (artifact_id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (log_id);


--
-- Name: checkpoints checkpoints_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.checkpoints
    ADD CONSTRAINT checkpoints_pkey PRIMARY KEY (checkpoint_id);


--
-- Name: code_types code_types_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.code_types
    ADD CONSTRAINT code_types_pkey PRIMARY KEY (code_type_id);


--
-- Name: codes codes_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.codes
    ADD CONSTRAINT codes_pkey PRIMARY KEY (code_id);


--
-- Name: configs configs_config_key_key; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.configs
    ADD CONSTRAINT configs_config_key_key UNIQUE (config_key);


--
-- Name: configs configs_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.configs
    ADD CONSTRAINT configs_pkey PRIMARY KEY (config_id);


--
-- Name: conversation_summaries conversation_summaries_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.conversation_summaries
    ADD CONSTRAINT conversation_summaries_pkey PRIMARY KEY (summary_id);


--
-- Name: conversations conversations_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (conversation_id);


--
-- Name: credential_bindings credential_bindings_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.credential_bindings
    ADD CONSTRAINT credential_bindings_pkey PRIMARY KEY (binding_id);


--
-- Name: credential_providers credential_providers_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.credential_providers
    ADD CONSTRAINT credential_providers_pkey PRIMARY KEY (provider_key);


--
-- Name: credential_vault credential_vault_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.credential_vault
    ADD CONSTRAINT credential_vault_pkey PRIMARY KEY (credential_id);


--
-- Name: files files_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.files
    ADD CONSTRAINT files_pkey PRIMARY KEY (file_id);


--
-- Name: integrations integrations_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.integrations
    ADD CONSTRAINT integrations_pkey PRIMARY KEY (integration_id);


--
-- Name: integrations integrations_service_key_key; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.integrations
    ADD CONSTRAINT integrations_service_key_key UNIQUE (service_key);


--
-- Name: messages messages_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (message_id);


--
-- Name: migration_history migration_history_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.migration_history
    ADD CONSTRAINT migration_history_pkey PRIMARY KEY (migration_id);


--
-- Name: migration_history migration_history_version_key; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.migration_history
    ADD CONSTRAINT migration_history_version_key UNIQUE (version);


--
-- Name: modules modules_module_key_key; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.modules
    ADD CONSTRAINT modules_module_key_key UNIQUE (module_key);


--
-- Name: modules modules_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.modules
    ADD CONSTRAINT modules_pkey PRIMARY KEY (module_id);


--
-- Name: processed_emails processed_emails_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.processed_emails
    ADD CONSTRAINT processed_emails_pkey PRIMARY KEY (message_id, queue_id);


--
-- Name: transcript_logs transcript_logs_pkey; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.transcript_logs
    ADD CONSTRAINT transcript_logs_pkey PRIMARY KEY (log_id);


--
-- Name: credential_bindings uq_binding; Type: CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.credential_bindings
    ADD CONSTRAINT uq_binding UNIQUE (context_type, context_id, provider_key);


--
-- Name: idx_agents_app; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_agents_app ON ag_agents.definitions USING btree (app_id);


--
-- Name: idx_agents_enabled; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_agents_enabled ON ag_agents.definitions USING btree (enabled) WHERE (enabled = true);


--
-- Name: idx_agents_owner; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_agents_owner ON ag_agents.definitions USING btree (owner_id);


--
-- Name: idx_cron_app; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_cron_app ON ag_agents.cron_jobs USING btree (app_id);


--
-- Name: idx_cron_jobs_active; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_cron_jobs_active ON ag_agents.cron_jobs USING btree (is_active) WHERE (is_active = true);


--
-- Name: idx_cron_jobs_next_run; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_cron_jobs_next_run ON ag_agents.cron_jobs USING btree (next_run_at) WHERE (is_active = true);


--
-- Name: idx_cron_outputs_job; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_cron_outputs_job ON ag_agents.cron_job_outputs USING btree (job_id);


--
-- Name: idx_outbox_due; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_outbox_due ON ag_agents.delivery_outbox USING btree (next_retry_at) WHERE ((status)::text = 'pending'::text);


--
-- Name: idx_runs_agent; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_runs_agent ON ag_agents.runs USING btree (agent_id);


--
-- Name: idx_runs_agent_time; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_runs_agent_time ON ag_agents.runs USING btree (agent_id, started_at DESC);


--
-- Name: idx_runs_status; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_runs_status ON ag_agents.runs USING btree (status);


--
-- Name: idx_runs_time; Type: INDEX; Schema: ag_agents; Owner: -
--

CREATE INDEX idx_runs_time ON ag_agents.runs USING btree (started_at DESC);


--
-- Name: idx_grant_lookup; Type: INDEX; Schema: ag_api; Owner: -
--

CREATE INDEX idx_grant_lookup ON ag_api.integration_grants USING btree (scope, ref);


--
-- Name: idx_op_embed; Type: INDEX; Schema: ag_api; Owner: -
--

CREATE INDEX idx_op_embed ON ag_api.operations USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_op_enabled; Type: INDEX; Schema: ag_api; Owner: -
--

CREATE INDEX idx_op_enabled ON ag_api.operations USING btree (integration_id, enabled);


--
-- Name: idx_op_tool; Type: INDEX; Schema: ag_api; Owner: -
--

CREATE INDEX idx_op_tool ON ag_api.operations USING btree (tool_name);


--
-- Name: idx_api_keys_hash; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_api_keys_hash ON ag_auth.api_keys USING btree (key_hash) WHERE (is_active = true);


--
-- Name: idx_api_keys_user; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_api_keys_user ON ag_auth.api_keys USING btree (user_id);


--
-- Name: idx_memberships_group; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_memberships_group ON ag_auth.memberships USING btree (group_ext_id);


--
-- Name: idx_memberships_user; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_memberships_user ON ag_auth.memberships USING btree (user_ext_id);


--
-- Name: idx_password_otps_user; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_password_otps_user ON ag_auth.password_otps USING btree (user_id, created_at DESC);


--
-- Name: idx_perm_overrides_user; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_perm_overrides_user ON ag_auth.user_permission_overrides USING btree (user_id);


--
-- Name: idx_refresh_tokens_active; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_refresh_tokens_active ON ag_auth.refresh_tokens USING btree (token) WHERE (is_active = true);


--
-- Name: idx_refresh_tokens_user; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_refresh_tokens_user ON ag_auth.refresh_tokens USING btree (user_id);


--
-- Name: idx_sessions_user; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_sessions_user ON ag_auth.user_sessions USING btree (user_id);


--
-- Name: idx_users_email; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_users_email ON ag_auth.users USING btree (email);


--
-- Name: idx_users_external; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_users_external ON ag_auth.users USING btree (external_id);


--
-- Name: idx_users_role; Type: INDEX; Schema: ag_auth; Owner: -
--

CREATE INDEX idx_users_role ON ag_auth.users USING btree (role_id);


--
-- Name: bots_publishable_key_uq; Type: INDEX; Schema: ag_bot; Owner: -
--

CREATE UNIQUE INDEX bots_publishable_key_uq ON ag_bot.bots USING btree (publishable_key);


--
-- Name: idx_bot_conv_session; Type: INDEX; Schema: ag_bot; Owner: -
--

CREATE INDEX idx_bot_conv_session ON ag_bot.bot_conversations USING btree (bot_id, session_id);


--
-- Name: idx_bot_conv_updated; Type: INDEX; Schema: ag_bot; Owner: -
--

CREATE INDEX idx_bot_conv_updated ON ag_bot.bot_conversations USING btree (bot_id, updated_at DESC);


--
-- Name: idx_bot_msg_conv; Type: INDEX; Schema: ag_bot; Owner: -
--

CREATE INDEX idx_bot_msg_conv ON ag_bot.bot_messages USING btree (conversation_id, created_at);


--
-- Name: idx_bot_rules_bot; Type: INDEX; Schema: ag_bot; Owner: -
--

CREATE INDEX idx_bot_rules_bot ON ag_bot.bot_rules USING btree (bot_id, is_active, priority DESC);


--
-- Name: idx_bots_app; Type: INDEX; Schema: ag_bot; Owner: -
--

CREATE INDEX idx_bots_app ON ag_bot.bots USING btree (app_id);


--
-- Name: idx_bots_token_hash; Type: INDEX; Schema: ag_bot; Owner: -
--

CREATE UNIQUE INDEX idx_bots_token_hash ON ag_bot.bots USING btree (api_token_hash);


--
-- Name: idx_embed_audit_integration; Type: INDEX; Schema: ag_bot; Owner: -
--

CREATE INDEX idx_embed_audit_integration ON ag_bot.embed_action_audit USING btree (integration_id, created_at DESC);


--
-- Name: idx_embed_audit_session; Type: INDEX; Schema: ag_bot; Owner: -
--

CREATE INDEX idx_embed_audit_session ON ag_bot.embed_action_audit USING btree (session_id, created_at);


--
-- Name: idx_answer_bundle; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_answer_bundle ON ag_brain.answer_cache USING btree (bundle_name);


--
-- Name: idx_brain_entities_app; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_brain_entities_app ON ag_brain.entities USING btree (app_id);


--
-- Name: idx_brain_entities_fts; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_brain_entities_fts ON ag_brain.entities USING gin (fts_vector);


--
-- Name: idx_brain_entities_name; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_brain_entities_name ON ag_brain.entities USING btree (name);


--
-- Name: idx_brain_entities_owner; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_brain_entities_owner ON ag_brain.entities USING btree (owner_id);


--
-- Name: idx_brain_entities_type; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_brain_entities_type ON ag_brain.entities USING btree (entity_type);


--
-- Name: idx_brain_rels_from; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_brain_rels_from ON ag_brain.relations USING btree (from_entity_id);


--
-- Name: idx_brain_rels_to; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_brain_rels_to ON ag_brain.relations USING btree (to_entity_id);


--
-- Name: idx_brain_rels_type; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_brain_rels_type ON ag_brain.relations USING btree (relation_type);


--
-- Name: idx_cache_app; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_cache_app ON ag_brain.content_cache USING btree (app_id);


--
-- Name: idx_cache_expiry; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_cache_expiry ON ag_brain.content_cache USING btree (fetched_at, ttl_seconds);


--
-- Name: idx_cache_owner; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_cache_owner ON ag_brain.content_cache USING btree (owner_id);


--
-- Name: idx_cache_source_type; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_cache_source_type ON ag_brain.content_cache USING btree (source_type);


--
-- Name: idx_chunks_doc; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_chunks_doc ON ag_brain.document_chunks USING btree (doc_id);


--
-- Name: idx_chunks_embedding; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_chunks_embedding ON ag_brain.document_chunks USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_dis_due; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_dis_due ON ag_brain.document_index_state USING btree (next_retry_at) WHERE (state = ANY (ARRAY['pending'::text, 'failed'::text]));


--
-- Name: idx_docs_app; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_app ON ag_brain.documents USING btree (app_id);


--
-- Name: idx_docs_created; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_created ON ag_brain.documents USING btree (created_at DESC);


--
-- Name: idx_docs_embedding; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_embedding ON ag_brain.documents USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_docs_fts; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_fts ON ag_brain.documents USING gin (fts_vector);


--
-- Name: idx_docs_hash; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_hash ON ag_brain.documents USING btree (content_hash);


--
-- Name: idx_docs_owner; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_owner ON ag_brain.documents USING btree (owner_id);


--
-- Name: idx_docs_owner_type; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_owner_type ON ag_brain.documents USING btree (owner_id, doc_type);


--
-- Name: idx_docs_source; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_source ON ag_brain.documents USING btree (source_path);


--
-- Name: idx_docs_status; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_status ON ag_brain.documents USING btree (status);


--
-- Name: idx_docs_tags; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_tags ON ag_brain.documents USING gin (tags);


--
-- Name: idx_docs_type; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_docs_type ON ag_brain.documents USING btree (doc_type);


--
-- Name: idx_ingestion_doc; Type: INDEX; Schema: ag_brain; Owner: -
--

CREATE INDEX idx_ingestion_doc ON ag_brain.ingestion_log USING btree (doc_id);


--
-- Name: idx_conn_owner; Type: INDEX; Schema: ag_cred; Owner: -
--

CREATE INDEX idx_conn_owner ON ag_cred.connections USING btree (scope, owner_ref);


--
-- Name: idx_conn_provider; Type: INDEX; Schema: ag_cred; Owner: -
--

CREATE INDEX idx_conn_provider ON ag_cred.connections USING btree (provider_key);


--
-- Name: idx_mem_app; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_app ON ag_memory.memories USING btree (app_id);


--
-- Name: idx_mem_entities_name; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_entities_name ON ag_memory.entities USING btree (name);


--
-- Name: idx_mem_entities_type; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_entities_type ON ag_memory.entities USING btree (entity_type);


--
-- Name: idx_mem_entities_user; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_entities_user ON ag_memory.entities USING btree (user_id);


--
-- Name: idx_mem_expires; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_expires ON ag_memory.memories USING btree (expires_at) WHERE (expires_at IS NOT NULL);


--
-- Name: idx_mem_fts; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_fts ON ag_memory.memories USING gin (fts_vector);


--
-- Name: idx_mem_tags_tag; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_tags_tag ON ag_memory.memory_tags USING btree (tag);


--
-- Name: idx_mem_user_cat; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_user_cat ON ag_memory.memories USING btree (user_id, category);


--
-- Name: idx_mem_user_key; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_user_key ON ag_memory.memories USING btree (user_id, key);


--
-- Name: idx_mem_user_layer; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_user_layer ON ag_memory.memories USING btree (user_id, layer);


--
-- Name: idx_mem_user_layer_cat; Type: INDEX; Schema: ag_memory; Owner: -
--

CREATE INDEX idx_mem_user_layer_cat ON ag_memory.memories USING btree (user_id, layer, category);


--
-- Name: idx_notif_recipients_notification_id; Type: INDEX; Schema: ag_notification; Owner: -
--

CREATE INDEX idx_notif_recipients_notification_id ON ag_notification.notification_recipients USING btree (notification_id);


--
-- Name: idx_notif_recipients_user_id; Type: INDEX; Schema: ag_notification; Owner: -
--

CREATE INDEX idx_notif_recipients_user_id ON ag_notification.notification_recipients USING btree (user_id);


--
-- Name: idx_action_audit_tool; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_action_audit_tool ON ag_system.action_audit USING btree (tool_name, created_at DESC);


--
-- Name: idx_action_audit_user; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_action_audit_user ON ag_system.action_audit USING btree (user_id, created_at DESC);


--
-- Name: idx_artifact_session; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_artifact_session ON ag_system.artifacts USING btree (session_id);


--
-- Name: idx_audit_action; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_audit_action ON ag_system.audit_log USING btree (action);


--
-- Name: idx_audit_entity_time; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_audit_entity_time ON ag_system.audit_log USING btree (entity_type, created_at DESC);


--
-- Name: idx_audit_time; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_audit_time ON ag_system.audit_log USING btree (created_at DESC);


--
-- Name: idx_audit_user; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_audit_user ON ag_system.audit_log USING btree (user_id);


--
-- Name: idx_binding_context; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_binding_context ON ag_system.credential_bindings USING btree (context_type, context_id);


--
-- Name: idx_binding_cred; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_binding_cred ON ag_system.credential_bindings USING btree (credential_id);


--
-- Name: idx_checkpoint_session; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_checkpoint_session ON ag_system.checkpoints USING btree (session_id);


--
-- Name: idx_conversations_archived; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_conversations_archived ON ag_system.conversations USING btree (user_id, is_archived);


--
-- Name: idx_conversations_processing; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_conversations_processing ON ag_system.conversations USING btree (conversation_id, processing_until);


--
-- Name: idx_conversations_source; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_conversations_source ON ag_system.conversations USING btree (user_id, source, updated_at DESC);


--
-- Name: idx_conversations_user; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_conversations_user ON ag_system.conversations USING btree (user_id, updated_at DESC);


--
-- Name: idx_messages_conv; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_messages_conv ON ag_system.messages USING btree (conversation_id, created_at);


--
-- Name: idx_personas_app; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_personas_app ON ag_system.agent_personas USING btree (app_id, is_active);


--
-- Name: idx_summaries_session; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_summaries_session ON ag_system.conversation_summaries USING btree (session_id);


--
-- Name: idx_summaries_user; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_summaries_user ON ag_system.conversation_summaries USING btree (user_id);


--
-- Name: idx_transcript_session; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_transcript_session ON ag_system.transcript_logs USING btree (session_id);


--
-- Name: idx_transcript_time; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_transcript_time ON ag_system.transcript_logs USING btree (created_at DESC);


--
-- Name: idx_transcript_user; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_transcript_user ON ag_system.transcript_logs USING btree (user_id);


--
-- Name: idx_vault_active; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_vault_active ON ag_system.credential_vault USING btree (provider_key, owner_id) WHERE (is_active = true);


--
-- Name: idx_vault_owner; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_vault_owner ON ag_system.credential_vault USING btree (owner_type, owner_id);


--
-- Name: idx_vault_provider; Type: INDEX; Schema: ag_system; Owner: -
--

CREATE INDEX idx_vault_provider ON ag_system.credential_vault USING btree (provider_key);


--
-- Name: cron_jobs trg_updated_at; Type: TRIGGER; Schema: ag_agents; Owner: -
--

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_agents.cron_jobs FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: definitions trg_updated_at; Type: TRIGGER; Schema: ag_agents; Owner: -
--

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_agents.definitions FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: users trg_updated_at; Type: TRIGGER; Schema: ag_auth; Owner: -
--

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_auth.users FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: bot_conversations trg_bot_conv_updated_at; Type: TRIGGER; Schema: ag_bot; Owner: -
--

CREATE TRIGGER trg_bot_conv_updated_at BEFORE UPDATE ON ag_bot.bot_conversations FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: bots trg_bots_updated_at; Type: TRIGGER; Schema: ag_bot; Owner: -
--

CREATE TRIGGER trg_bots_updated_at BEFORE UPDATE ON ag_bot.bots FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: documents trg_updated_at; Type: TRIGGER; Schema: ag_brain; Owner: -
--

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_brain.documents FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: entities trg_updated_at; Type: TRIGGER; Schema: ag_brain; Owner: -
--

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_brain.entities FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: sync_state trg_updated_at; Type: TRIGGER; Schema: ag_brain; Owner: -
--

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_brain.sync_state FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: memories trg_updated_at; Type: TRIGGER; Schema: ag_memory; Owner: -
--

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_memory.memories FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: agent_personas trg_agent_personas_updated_at; Type: TRIGGER; Schema: ag_system; Owner: -
--

CREATE TRIGGER trg_agent_personas_updated_at BEFORE UPDATE ON ag_system.agent_personas FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: messages trg_message_update_conv_ts; Type: TRIGGER; Schema: ag_system; Owner: -
--

CREATE TRIGGER trg_message_update_conv_ts AFTER INSERT ON ag_system.messages FOR EACH ROW EXECUTE FUNCTION ag_system.update_conversation_timestamp();


--
-- Name: configs trg_updated_at; Type: TRIGGER; Schema: ag_system; Owner: -
--

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_system.configs FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: integrations trg_updated_at; Type: TRIGGER; Schema: ag_system; Owner: -
--

CREATE TRIGGER trg_updated_at BEFORE UPDATE ON ag_system.integrations FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


--
-- Name: cron_job_outputs cron_job_outputs_job_id_fkey; Type: FK CONSTRAINT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.cron_job_outputs
    ADD CONSTRAINT cron_job_outputs_job_id_fkey FOREIGN KEY (job_id) REFERENCES ag_agents.cron_jobs(job_id) ON DELETE CASCADE;


--
-- Name: cron_jobs cron_jobs_app_id_fkey; Type: FK CONSTRAINT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.cron_jobs
    ADD CONSTRAINT cron_jobs_app_id_fkey FOREIGN KEY (app_id) REFERENCES ag_system.applications(app_id);


--
-- Name: definitions definitions_app_id_fkey; Type: FK CONSTRAINT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.definitions
    ADD CONSTRAINT definitions_app_id_fkey FOREIGN KEY (app_id) REFERENCES ag_system.applications(app_id);


--
-- Name: runs runs_agent_id_fkey; Type: FK CONSTRAINT; Schema: ag_agents; Owner: -
--

ALTER TABLE ONLY ag_agents.runs
    ADD CONSTRAINT runs_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES ag_agents.definitions(agent_id) ON DELETE CASCADE;


--
-- Name: integration_grants integration_grants_integration_id_fkey; Type: FK CONSTRAINT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.integration_grants
    ADD CONSTRAINT integration_grants_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES ag_api.integrations(integration_id) ON DELETE CASCADE;


--
-- Name: integrations integrations_auth_provider_fkey; Type: FK CONSTRAINT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.integrations
    ADD CONSTRAINT integrations_auth_provider_fkey FOREIGN KEY (auth_provider) REFERENCES ag_cred.providers(provider_key);


--
-- Name: operations operations_integration_id_fkey; Type: FK CONSTRAINT; Schema: ag_api; Owner: -
--

ALTER TABLE ONLY ag_api.operations
    ADD CONSTRAINT operations_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES ag_api.integrations(integration_id) ON DELETE CASCADE;


--
-- Name: api_keys api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.api_keys
    ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES ag_auth.users(user_id) ON DELETE CASCADE;


--
-- Name: password_otps password_otps_user_id_fkey; Type: FK CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.password_otps
    ADD CONSTRAINT password_otps_user_id_fkey FOREIGN KEY (user_id) REFERENCES ag_auth.users(user_id) ON DELETE CASCADE;


--
-- Name: refresh_tokens refresh_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.refresh_tokens
    ADD CONSTRAINT refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES ag_auth.users(user_id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_module_id_fkey; Type: FK CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.role_permissions
    ADD CONSTRAINT role_permissions_module_id_fkey FOREIGN KEY (module_id) REFERENCES ag_system.modules(module_id) ON DELETE CASCADE;


--
-- Name: role_permissions role_permissions_role_id_fkey; Type: FK CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.role_permissions
    ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES ag_auth.roles(role_id) ON DELETE CASCADE;


--
-- Name: user_permission_overrides user_permission_overrides_module_id_fkey; Type: FK CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.user_permission_overrides
    ADD CONSTRAINT user_permission_overrides_module_id_fkey FOREIGN KEY (module_id) REFERENCES ag_system.modules(module_id) ON DELETE CASCADE;


--
-- Name: user_permission_overrides user_permission_overrides_user_id_fkey; Type: FK CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.user_permission_overrides
    ADD CONSTRAINT user_permission_overrides_user_id_fkey FOREIGN KEY (user_id) REFERENCES ag_auth.users(user_id) ON DELETE CASCADE;


--
-- Name: user_sessions user_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.user_sessions
    ADD CONSTRAINT user_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES ag_auth.users(user_id) ON DELETE CASCADE;


--
-- Name: users users_app_id_fkey; Type: FK CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.users
    ADD CONSTRAINT users_app_id_fkey FOREIGN KEY (app_id) REFERENCES ag_system.applications(app_id);


--
-- Name: users users_role_id_fkey; Type: FK CONSTRAINT; Schema: ag_auth; Owner: -
--

ALTER TABLE ONLY ag_auth.users
    ADD CONSTRAINT users_role_id_fkey FOREIGN KEY (role_id) REFERENCES ag_auth.roles(role_id);


--
-- Name: bot_conversations bot_conversations_bot_id_fkey; Type: FK CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bot_conversations
    ADD CONSTRAINT bot_conversations_bot_id_fkey FOREIGN KEY (bot_id) REFERENCES ag_bot.bots(bot_id) ON DELETE CASCADE;


--
-- Name: bot_messages bot_messages_conversation_id_fkey; Type: FK CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bot_messages
    ADD CONSTRAINT bot_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES ag_bot.bot_conversations(conversation_id) ON DELETE CASCADE;


--
-- Name: bot_rules bot_rules_bot_id_fkey; Type: FK CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bot_rules
    ADD CONSTRAINT bot_rules_bot_id_fkey FOREIGN KEY (bot_id) REFERENCES ag_bot.bots(bot_id) ON DELETE CASCADE;


--
-- Name: bots bots_app_id_fkey; Type: FK CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bots
    ADD CONSTRAINT bots_app_id_fkey FOREIGN KEY (app_id) REFERENCES ag_system.applications(app_id);


--
-- Name: bots bots_persona_id_fkey; Type: FK CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.bots
    ADD CONSTRAINT bots_persona_id_fkey FOREIGN KEY (persona_id) REFERENCES ag_system.agent_personas(persona_id);


--
-- Name: embed_action_audit embed_action_audit_integration_id_fkey; Type: FK CONSTRAINT; Schema: ag_bot; Owner: -
--

ALTER TABLE ONLY ag_bot.embed_action_audit
    ADD CONSTRAINT embed_action_audit_integration_id_fkey FOREIGN KEY (integration_id) REFERENCES ag_bot.bots(bot_id);


--
-- Name: content_cache content_cache_app_id_fkey; Type: FK CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.content_cache
    ADD CONSTRAINT content_cache_app_id_fkey FOREIGN KEY (app_id) REFERENCES ag_system.applications(app_id);


--
-- Name: document_chunks document_chunks_doc_id_fkey; Type: FK CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.document_chunks
    ADD CONSTRAINT document_chunks_doc_id_fkey FOREIGN KEY (doc_id) REFERENCES ag_brain.documents(doc_id) ON DELETE CASCADE;


--
-- Name: documents documents_app_id_fkey; Type: FK CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.documents
    ADD CONSTRAINT documents_app_id_fkey FOREIGN KEY (app_id) REFERENCES ag_system.applications(app_id);


--
-- Name: entities entities_app_id_fkey; Type: FK CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.entities
    ADD CONSTRAINT entities_app_id_fkey FOREIGN KEY (app_id) REFERENCES ag_system.applications(app_id);


--
-- Name: document_index_state fk_dis_doc; Type: FK CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.document_index_state
    ADD CONSTRAINT fk_dis_doc FOREIGN KEY (doc_id) REFERENCES ag_brain.documents(doc_id) ON DELETE CASCADE;


--
-- Name: ingestion_log ingestion_log_doc_id_fkey; Type: FK CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.ingestion_log
    ADD CONSTRAINT ingestion_log_doc_id_fkey FOREIGN KEY (doc_id) REFERENCES ag_brain.documents(doc_id) ON DELETE CASCADE;


--
-- Name: relations relations_from_entity_id_fkey; Type: FK CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.relations
    ADD CONSTRAINT relations_from_entity_id_fkey FOREIGN KEY (from_entity_id) REFERENCES ag_brain.entities(entity_id) ON DELETE CASCADE;


--
-- Name: relations relations_to_entity_id_fkey; Type: FK CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.relations
    ADD CONSTRAINT relations_to_entity_id_fkey FOREIGN KEY (to_entity_id) REFERENCES ag_brain.entities(entity_id) ON DELETE CASCADE;


--
-- Name: sync_state sync_state_app_id_fkey; Type: FK CONSTRAINT; Schema: ag_brain; Owner: -
--

ALTER TABLE ONLY ag_brain.sync_state
    ADD CONSTRAINT sync_state_app_id_fkey FOREIGN KEY (app_id) REFERENCES ag_system.applications(app_id);


--
-- Name: connections connections_provider_key_fkey; Type: FK CONSTRAINT; Schema: ag_cred; Owner: -
--

ALTER TABLE ONLY ag_cred.connections
    ADD CONSTRAINT connections_provider_key_fkey FOREIGN KEY (provider_key) REFERENCES ag_cred.providers(provider_key);


--
-- Name: memories memories_app_id_fkey; Type: FK CONSTRAINT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.memories
    ADD CONSTRAINT memories_app_id_fkey FOREIGN KEY (app_id) REFERENCES ag_system.applications(app_id);


--
-- Name: memory_tags memory_tags_memory_id_fkey; Type: FK CONSTRAINT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.memory_tags
    ADD CONSTRAINT memory_tags_memory_id_fkey FOREIGN KEY (memory_id) REFERENCES ag_memory.memories(memory_id) ON DELETE CASCADE;


--
-- Name: relations relations_source_id_fkey; Type: FK CONSTRAINT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.relations
    ADD CONSTRAINT relations_source_id_fkey FOREIGN KEY (source_id) REFERENCES ag_memory.entities(entity_id) ON DELETE CASCADE;


--
-- Name: relations relations_target_id_fkey; Type: FK CONSTRAINT; Schema: ag_memory; Owner: -
--

ALTER TABLE ONLY ag_memory.relations
    ADD CONSTRAINT relations_target_id_fkey FOREIGN KEY (target_id) REFERENCES ag_memory.entities(entity_id) ON DELETE CASCADE;


--
-- Name: notification_recipients notification_recipients_notification_id_fkey; Type: FK CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.notification_recipients
    ADD CONSTRAINT notification_recipients_notification_id_fkey FOREIGN KEY (notification_id) REFERENCES ag_notification.notifications(notification_id) ON DELETE CASCADE;


--
-- Name: notifications notifications_template_id_fkey; Type: FK CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.notifications
    ADD CONSTRAINT notifications_template_id_fkey FOREIGN KEY (template_id) REFERENCES ag_notification.push_notification_template(push_notification_template_id);


--
-- Name: push_notifications push_notifications_campaign_id_fkey; Type: FK CONSTRAINT; Schema: ag_notification; Owner: -
--

ALTER TABLE ONLY ag_notification.push_notifications
    ADD CONSTRAINT push_notifications_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES ag_notification.notifications(notification_id);


--
-- Name: agent_personas agent_personas_app_id_fkey; Type: FK CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.agent_personas
    ADD CONSTRAINT agent_personas_app_id_fkey FOREIGN KEY (app_id) REFERENCES ag_system.applications(app_id) ON DELETE CASCADE;


--
-- Name: codes codes_code_type_id_fkey; Type: FK CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.codes
    ADD CONSTRAINT codes_code_type_id_fkey FOREIGN KEY (code_type_id) REFERENCES ag_system.code_types(code_type_id);


--
-- Name: conversations conversations_user_id_fkey; Type: FK CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.conversations
    ADD CONSTRAINT conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES ag_auth.users(user_id);


--
-- Name: credential_bindings credential_bindings_credential_id_fkey; Type: FK CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.credential_bindings
    ADD CONSTRAINT credential_bindings_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES ag_system.credential_vault(credential_id) ON DELETE CASCADE;


--
-- Name: credential_bindings credential_bindings_provider_key_fkey; Type: FK CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.credential_bindings
    ADD CONSTRAINT credential_bindings_provider_key_fkey FOREIGN KEY (provider_key) REFERENCES ag_system.credential_providers(provider_key);


--
-- Name: credential_vault credential_vault_provider_key_fkey; Type: FK CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.credential_vault
    ADD CONSTRAINT credential_vault_provider_key_fkey FOREIGN KEY (provider_key) REFERENCES ag_system.credential_providers(provider_key);


--
-- Name: messages messages_conversation_id_fkey; Type: FK CONSTRAINT; Schema: ag_system; Owner: -
--

ALTER TABLE ONLY ag_system.messages
    ADD CONSTRAINT messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES ag_system.conversations(conversation_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict sGLf9DcFEdu9suuC6PafGvEM2b59EjIj6QjiBq1dbcL1qOxfNKLYWznq0NKvX5C


-- ===================== PLATFORM SEED DATA ======================
--
-- PostgreSQL database dump
--

\restrict QBIE3dsSrDyGPdIeGnkxhFYZ0CEEWrEVTNLP1LUeeVDePv7Uvq6leqipVVkNSIV

-- Dumped from database version 17.7 (Ubuntu 17.7-0ubuntu0.25.04.1)
-- Dumped by pg_dump version 17.7 (Ubuntu 17.7-0ubuntu0.25.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: roles; Type: TABLE DATA; Schema: ag_auth; Owner: -
--

COPY ag_auth.roles (role_id, role_key, role_name, description, is_system, created_at) FROM stdin;
1	owner	Tenant Owner	Full access including billing, user management, and system settings	t	2026-05-30 08:59:12.237631+05:30
2	admin	Administrator	Full access except billing and system settings	t	2026-05-30 08:59:12.237631+05:30
3	member	Member	Use AI agent, ingest documents, manage own memories and agents	t	2026-05-30 08:59:12.237631+05:30
4	viewer	Viewer	Read-only access to brain search and memory recall	t	2026-05-30 08:59:12.237631+05:30
5	agent	Service Agent	Service account for spawned AI agents and cron jobs	t	2026-05-30 08:59:12.237631+05:30
\.


--
-- Data for Name: modules; Type: TABLE DATA; Schema: ag_system; Owner: -
--

COPY ag_system.modules (module_id, module_name, module_key, description, is_active, created_at) FROM stdin;
1	AI Chat	ai_chat	Send messages to the AI agent and receive responses	t	2026-05-30 08:59:12.237631+05:30
2	Brain Search	brain_search	Search the knowledge base for information	t	2026-05-30 08:59:12.237631+05:30
3	Brain Ingest	brain_ingest	Ingest documents, URLs, and files into the brain	t	2026-05-30 08:59:12.237631+05:30
4	Brain Sync	brain_sync	Configure and run data source synchronization	t	2026-05-30 08:59:12.237631+05:30
5	Memory Management	memory_mgmt	Store, recall, and manage persistent memories	t	2026-05-30 08:59:12.237631+05:30
6	Agent Management	agent_mgmt	Create, edit, and manage custom AI agents	t	2026-05-30 08:59:12.237631+05:30
7	Cron Management	cron_mgmt	Schedule and manage recurring agent tasks	t	2026-05-30 08:59:12.237631+05:30
8	File Operations	file_ops	Read, write, and manage files in workspace	t	2026-05-30 08:59:12.237631+05:30
9	Code Operations	code_ops	Execute code, run commands, and terminal operations	t	2026-05-30 08:59:12.237631+05:30
10	User Management	user_mgmt	Add, edit, and deactivate tenant users	t	2026-05-30 08:59:12.237631+05:30
11	Integration Config	integration_config	Configure external service connections (Jira, Slack, etc.)	t	2026-05-30 08:59:12.237631+05:30
12	System Settings	system_settings	Manage tenant-level configuration and API keys	t	2026-05-30 08:59:12.237631+05:30
\.


--
-- Data for Name: role_permissions; Type: TABLE DATA; Schema: ag_auth; Owner: -
--

COPY ag_auth.role_permissions (role_id, module_id, can_create, can_read, can_update, can_delete) FROM stdin;
1	1	t	t	t	t
1	2	t	t	t	t
1	3	t	t	t	t
1	4	t	t	t	t
1	5	t	t	t	t
1	6	t	t	t	t
1	7	t	t	t	t
1	8	t	t	t	t
1	9	t	t	t	t
1	10	t	t	t	t
1	11	t	t	t	t
1	12	t	t	t	t
2	1	t	t	t	t
2	2	t	t	t	t
2	3	t	t	t	t
2	4	t	t	t	t
2	5	t	t	t	t
2	6	t	t	t	t
2	7	t	t	t	t
2	8	t	t	t	t
2	9	t	t	t	t
2	10	t	t	t	t
2	11	t	t	t	t
2	12	f	t	f	f
3	1	t	t	f	f
3	2	f	t	f	f
3	3	t	t	f	f
3	4	f	t	f	f
3	5	t	t	t	t
3	6	t	t	t	t
3	7	f	t	f	f
3	8	t	t	f	f
3	9	t	t	f	f
4	1	f	t	f	f
4	2	f	t	f	f
4	5	f	t	f	f
5	1	f	t	f	f
5	2	f	t	f	f
5	3	t	t	f	f
5	5	t	t	t	f
5	8	t	t	f	f
5	9	t	t	f	f
\.


--
-- Data for Name: providers; Type: TABLE DATA; Schema: ag_cred; Owner: -
--

COPY ag_cred.providers (provider_key, display_name, category, kind, fields, supports_user, supports_verify, is_active, sort_order, icon_url, docs_url, created_at) FROM stdin;
jira	Jira Cloud	integration	direct	[{"key": "server_url", "help": "Your Atlassian Cloud or Server instance URL", "type": "url", "label": "Jira Server URL", "scope": "both", "secret": false, "required": true, "placeholder": "https://your-domain.atlassian.net"}, {"key": "email", "help": "Email associated with your Atlassian account", "type": "email", "label": "Account Email", "scope": "both", "secret": false, "required": true, "placeholder": "you@company.com"}, {"key": "api_token", "help": "id.atlassian.com > Security > API tokens", "type": "password", "label": "API Token", "scope": "both", "secret": true, "required": true, "placeholder": "Enter your Jira API token"}]	t	t	t	20	\N	\N	2026-06-21 14:48:54.765697+05:30
m365	Microsoft 365 (Outlook)	integration	shared_app	[{"key": "tenant_id", "help": "Azure Portal > Microsoft Entra ID > Overview. Set once by an admin.", "type": "text", "label": "Azure AD Tenant ID", "scope": "org", "secret": false, "required": true, "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}, {"key": "client_id", "help": "App Registration > Overview. Set once by an admin.", "type": "text", "label": "Application (Client) ID", "scope": "org", "secret": false, "required": true, "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}, {"key": "client_secret", "help": "App Registration > Certificates & Secrets > Value. Set once by an admin.", "type": "password", "label": "Client Secret Value", "scope": "org", "secret": true, "required": true, "placeholder": "Enter the client secret value"}, {"key": "user_email", "help": "The mailbox the agent should access — usually your own work email.", "type": "email", "label": "Mailbox Email", "scope": "identity", "secret": false, "required": true, "placeholder": "you@company.com"}]	t	t	t	21	\N	\N	2026-06-21 14:48:54.765697+05:30
smtp	SMTP Email	integration	direct	[{"key": "server", "help": "SMTP server hostname", "type": "text", "label": "SMTP Server", "scope": "both", "secret": false, "required": true, "placeholder": "smtp.gmail.com"}, {"key": "port", "help": "Usually 587 (TLS) or 465 (SSL)", "type": "number", "label": "Port", "scope": "both", "secret": false, "required": true, "placeholder": "587"}, {"key": "username", "help": "SMTP authentication username", "type": "text", "label": "Username / Email", "scope": "both", "secret": false, "required": true, "placeholder": "you@gmail.com"}, {"key": "use_tls", "type": "boolean", "label": "Use TLS", "scope": "both", "secret": false, "default": true, "required": false}, {"key": "password", "help": "For Gmail, use an App Password", "type": "password", "label": "Password / App Password", "scope": "both", "secret": true, "required": true, "placeholder": "Enter password"}]	t	t	t	22	\N	\N	2026-06-21 14:48:54.765697+05:30
imap	IMAP Email	integration	direct	[{"key": "server", "help": "IMAP server hostname", "type": "text", "label": "IMAP Server", "scope": "both", "secret": false, "required": true, "placeholder": "imap.gmail.com"}, {"key": "port", "help": "Usually 993 (SSL)", "type": "number", "label": "Port", "scope": "both", "secret": false, "required": false, "placeholder": "993"}, {"key": "username", "help": "IMAP authentication username", "type": "text", "label": "Username / Email", "scope": "both", "secret": false, "required": true, "placeholder": "you@gmail.com"}, {"key": "use_ssl", "type": "boolean", "label": "Use SSL", "scope": "both", "secret": false, "default": true, "required": false}, {"key": "password", "help": "For Gmail, use an App Password", "type": "password", "label": "Password / App Password", "scope": "both", "secret": true, "required": true, "placeholder": "Enter password"}]	t	t	t	23	\N	\N	2026-06-21 14:48:54.765697+05:30
confluence	Confluence	integration	direct	[{"key": "url", "help": "Your Confluence base URL", "type": "url", "label": "Base URL", "scope": "both", "secret": false, "required": true, "placeholder": "https://your-domain.atlassian.net/wiki"}, {"key": "email", "help": "Email associated with your Atlassian account", "type": "email", "label": "Account Email", "scope": "both", "secret": false, "required": true, "placeholder": "you@company.com"}, {"key": "api_token", "help": "id.atlassian.com > Security > API tokens", "type": "password", "label": "API Token", "scope": "both", "secret": true, "required": true, "placeholder": "Enter your API token"}]	t	t	t	24	\N	\N	2026-06-21 14:48:54.765697+05:30
telegram	Telegram (personal bot)	channel	direct	[{"key": "bot_token", "help": "Create a bot with @BotFather in Telegram and paste the token it gives you.", "type": "password", "label": "Bot Token", "scope": "both", "secret": true, "required": true, "placeholder": "123456789:ABCdef..."}]	t	t	t	30	\N	\N	2026-06-27 10:41:42.789776+05:30
api_fleet	Fleet API	api	direct	[{"key": "username", "type": "text", "label": "Username / Email", "scope": "identity", "secret": false, "required": true}, {"key": "password", "help": "Used once to obtain a token; only a refresh token is stored — never your password.", "type": "password", "label": "Password", "scope": "identity", "secret": true, "required": true}]	t	t	t	500	\N	\N	2026-06-26 16:49:00.016904+05:30
\.


--
-- Data for Name: applications; Type: TABLE DATA; Schema: ag_system; Owner: -
--

COPY ag_system.applications (app_id, app_uuid, name, description, app_type, llm_model, llm_api_key_enc, max_tokens_day, max_documents, is_active, created_by, created_at, updated_at) FROM stdin;
1	4632529f-df27-4b44-b842-cabdc9bcad3e	Internal AI Assistant	Default internal AI assistant for admin dashboard and web chat	internal	\N	\N	0	0	t	1	2026-06-01 20:41:38.631152+05:30	2026-06-01 20:41:38.631152+05:30
2	08c69ab2-c1ef-4868-8c9b-e493339c4cda	Email Triage	Automated email ingestion and ticket creation from cron jobs	internal	\N	\N	0	0	t	1	2026-06-01 20:41:38.631152+05:30	2026-06-01 20:41:38.631152+05:30
4	01adb238-af44-4927-92d4-2f7c7be37bd5	Fleet Support	Customer-facing support chatbot for Fleet application	chatbot	\N	\N	0	0	t	1	2026-06-05 10:44:39.763621+05:30	2026-06-05 10:44:39.763621+05:30
3	cd643e04-cdbb-4b3c-9ec5-feb0f759b472	SMSystem Support	Customer-facing support chatbot for SMSystem application	chatbot	\N	\N	0	0	f	1	2026-06-01 20:41:38.631152+05:30	2026-06-21 13:37:09.743007+05:30
5	22f8f305-e052-44f6-a686-a4ef9e20a8b0	Web Copilot	AI-powered web copilot that helps users browse, understand content, and get AI assistance for web-related tasks	chatbot	\N	\N	0	0	f	1	2026-06-14 15:34:38.469216+05:30	2026-06-21 13:37:18.845426+05:30
\.


--
-- Data for Name: agent_personas; Type: TABLE DATA; Schema: ag_system; Owner: -
--

COPY ag_system.agent_personas (persona_id, app_id, name, description, identity_prompt, constraints_prompt, communication_prompt, allowed_tools, disable_passivity_correction, is_default, is_active, created_at, updated_at, input_guardrail_prompt, execution_policies, output_dlp_patterns, output_semantic_rules, approval_mode) FROM stdin;
4	2	Email Triage Agent	Automated email triage and routing agent	You are the Email Triage Agent. Your role is to fetch, analyze, categorize, and route incoming emails. You can create Jira tickets for support issues and respond to routine inquiries.	You MAY access emails and Jira for triage purposes. You MUST NOT run shell commands, modify files, or access code repositories. You MUST NOT expose internal system details to external contacts. When creating Jira tickets, use appropriate labels and priorities based on email content.	Be concise and structured. Categorize emails clearly. Use markdown formatting.	["fetch_recent_emails", "search_emails", "mark_email_processed", "outlook_reply", "outlook_send", "outlook_forward", "brain_ask", "brain_search", "brain_stats", "brain_sync", "jira_create_ticket", "jira_update_ticket", "jira_list_tickets", "memory_recall", "memory_store", "search_web", "send_email_smtp", "fetch_emails_imap"]	t	t	t	2026-06-06 21:48:40.653481+05:30	2026-06-06 21:48:40.653481+05:30	\N	{}	[]	\N	\N
1	3	SMSystem Public Bot	Restricted customer support persona for SMSystem chatbot	You are the SMSystem Support Assistant, a helpful and professional chatbot for the SMSystem application by Storeglance. Answer questions about SMSystem features, pricing, and capabilities. Help users troubleshoot common issues and guide them through the application.	STRICT CONSTRAINTS:\n1. NEVER access emails, shell commands, or file systems.\n2. NEVER expose internal tool names, API endpoints, database schemas, or source code.\n3. NEVER share Jira ticket IDs, internal URLs, or system architecture details.\n4. If you do not know something, say so honestly and suggest contacting support@storeglance.com.\n5. Always respond in the same language the user writes in.\n6. Keep responses under 500 words unless the user asks for detail.	Be polite, concise, and accurate. Use markdown formatting for better readability.	["brain_ask", "brain_search", "brain_stats", "search_web"]	t	t	t	2026-06-06 21:29:43.347906+05:30	2026-06-14 10:49:56.130165+05:30	\N	{"$mode": "whitelist", "brain_ask": null, "search_web": null, "brain_stats": null, "brain_search": null}	[]	\N	\N
5	5	Web Copilot Assistant	AI assistant that helps users navigate the web, find information, and complete tasks	You are Web Copilot, an intelligent AI assistant designed to help users with web-related tasks. You are knowledgeable, helpful, and proactive. You assist users in browsing the web, finding accurate information, summarizing content, extracting key data from web pages, researching topics, and completing online tasks efficiently. You act as the user's co-pilot for the internet — guiding them, providing context, and making their web experience smoother and more productive.\n\nYou also act as an IN-APP copilot embedded in the current web application. You can SEE and OPERATE the screen the user is on — its menus, sidebars, forms, and buttons — to carry out tasks they ask for. Navigate by observing the page and CLICKING the real on-screen menu/sidebar links (page_observe then page_act), never by guessing route URLs. After every click or navigation, observe the screen again before acting.	1. Always prioritize factual accuracy — verify information when uncertain.\n2. Do not execute irreversible actions (deletions, destructive writes) without user confirmation.\n3. Respect user privacy — never share personal user data outside the conversation.\n4. When searching the web, provide the source URL alongside any information.\n5. If you cannot find reliable information, be honest about it instead of making things up.\n6. Keep conversations focused on helping the user achieve their web-related goals.	Be concise, clear, and helpful. Use markdown formatting for readability. When sharing web search results, always cite sources with links. Summarize complex information before diving into details. Use a friendly, professional tone — you're a copilot, not a robot. Break down complex tasks into simple steps.	["search_web", "brain_ask", "brain_search", "ask_question", "memory_recall", "get_memories", "page_observe", "page_act", "page_navigate", "page_wait", "page_read"]	t	t	t	2026-06-14 15:35:24.94791+05:30	2026-06-15 09:56:38.595001+05:30	\N	{}	[]	\N	\N
3	1	Internal AI Agent	Full-power internal AI agent with all tools for development team	You are Agent, an autonomous AI coding agent. You pair-program with the user to solve coding tasks — creating, modifying, debugging, or explaining codebases. You have a persistent brain/knowledge system (MCP tools prefixed brain_ and memory_). When the user asks about mcp data, brain data, knowledge base, or what is in memory, use brain_stats to check the data store and brain_search to find specific content.	You do NOT have a code interpreter. All execution happens via tools. Shell output is capped at 50KB. File reads capped at 800 lines. Maintain documentation integrity: preserve existing comments unrelated to your changes. Always attempt tool calls before concluding something is impossible. CRITICAL: To schedule background or cron tasks, you MUST use the cron_create tool. DO NOT hallucinate terminal commands like gcr or crontab.	Concise. No filler. Markdown formatted. Summarize your work at the end of each turn.	["view_file", "write_to_file", "list_dir", "grep_search", "replace_file_content", "multi_replace_file_content", "run_command", "schedule", "manage_task", "cron_list", "cron_remove", "add_memory", "get_memories", "search_web", "ask_question", "query_neo4j", "search_elasticsearch", "fetch_recent_emails", "search_emails", "brain_ingest_file", "brain_ingest_directory", "brain_ingest_text", "brain_ingest_current_chat", "brain_ask", "brain_search", "brain_stats", "brain_sync", "brain_sync_status", "brain_fetch", "memory_recall", "memory_store", "memory_stats", "memory_forget", "memory_user_context", "memory_entity_link", "memory_company_store", "mark_email_processed", "agent_create", "agent_list", "agent_run", "agent_delete", "agent_logs", "outlook_reply", "outlook_send", "outlook_forward", "teams_send_message", "teams_post_channel", "teams_list_channels", "send_email_smtp", "fetch_emails_imap", "jira_create_ticket", "jira_update_ticket", "jira_list_tickets", "git_branch", "git_commit", "git_status", "git_diff", "page_navigate", "page_wait", "page_read", "page_observe", "page_act"]	f	t	t	2026-06-06 21:48:40.653481+05:30	2026-06-19 18:39:15.378467+05:30	\N	{}	[]	\N	\N
2	4	Fleet Public Bot	Restricted customer support persona for Fleet Management chatbot	You are the Antigravity Fleet Management Copilot — an AI assistant embedded directly on the Fleet Management site. You can SEE and CONTROL the page the user is currently viewing.\n\n## Your Capabilities\n1. **See the page**: Use page_snapshot to observe what is currently on screen — form fields, buttons, tables, dropdowns, navigation links.\n2. **Navigate**: Use page_navigate to go to different pages (e.g. /management/vehicle-list, /management/drivers).\n3. **Fill forms**: Use page_fill to type into text fields, page_select to choose dropdown options.\n4. **Click buttons**: Use page_click to click buttons, links, tabs, and interactive elements.\n5. **Read content**: Use page_read to read the full text content of the page.\n6. **Answer questions**: Use brain_ask / brain_search to look up Fleet Management documentation.\n\n## How to Help Users\n- When a user asks you to DO something (add a vehicle, fill a form, navigate), USE YOUR PAGE TOOLS to actually do it on their behalf.\n- ALWAYS start by calling page_snapshot to see what is currently on screen.\n- If the user is on the wrong page, use page_navigate to go to the right page first.\n- After filling a form or clicking, call page_snapshot again to verify the result.\n- If you need documentation about how something works, use brain_ask.\n\n## Important Rules\n- You are NOT a text-only assistant. You CAN and SHOULD interact with the page.\n- Never tell the user you cannot navigate or that you are just a support assistant — you ARE a copilot that drives the page.\n- Be proactive: if the user says "add a vehicle", navigate to the vehicle page, snapshot it, and start filling the form.\n- Always confirm what you did after completing an action.	STRICT SECRECY CONSTRAINTS:\n1. You are a public-facing customer support assistant. You must NEVER reveal or confirm any internal information, including emails, Jira tickets, Telegram messages, database schemas, system architecture, or internal tool names.\n2. Keep all technical operations completely invisible to the user. Do not explain your background processes or the tools you use. Focus entirely on providing helpful support.\n\nSMART ISSUE DEDUPLICATION WORKFLOW:\nWhen a user reports a bug or requests an operational change, execute this background workflow:\n1. Search: Use `jira_list_tickets` to search for existing issues.\n2. Deduplicate/Create: If a similar issue exists, use `jira_update_ticket` to add a comment. If not, use `jira_create_ticket` (Project key: SCRUM) to create a new one.\n3. Respond: Finally, provide the user with the helpful support instructions they asked for. If you reported a bug, add: "I have forwarded this to our operations team." \nCRITICAL: Under no circumstances should your final response include the word "Jira", "ticket", or mention your search process.\n\nANTI-PROBING RULE:\nIf the user explicitly asks to see their tickets, ticket statuses, or internal data, rigidly reply: "I am a customer support assistant. I can report issues for you, but for security reasons, I do not have permission to share internal engineering ticket details."	Be concise, friendly, and professional. Use markdown formatting. Keep responses under 500 words.	["brain_ask", "brain_search", "brain_stats", "search_web", "jira_create_ticket", "jira_list_tickets", "view_file", "manage_task", "write_to_file", "cron_list", "list_dir", "cron_remove", "add_memory", "grep_search", "get_memories", "replace_file_content", "multi_replace_file_content", "run_command", "ask_question", "schedule", "query_neo4j", "memory_stats", "memory_store", "brain_ingest_current_chat", "agent_list", "agent_run", "mark_email_processed", "brain_fetch", "brain_sync_status", "memory_company_store", "brain_ingest_file", "brain_ingest_directory", "brain_ingest_text", "search_emails", "brain_sync", "memory_entity_link", "memory_user_context", "fetch_recent_emails", "search_elasticsearch", "memory_forget", "agent_delete", "send_email_smtp", "git_diff", "agent_logs", "fetch_emails_imap", "outlook_reply", "outlook_send", "outlook_forward", "teams_send_message", "agent_create", "git_branch", "git_commit", "teams_post_channel", "teams_list_channels", "git_status", "page_snapshot", "page_fill", "page_select", "page_click", "page_observe", "jira_update_ticket", "page_act", "page_navigate", "page_read", "page_wait", "jira_add_worklog", "jira_transition_ticket", "jira_add_comment"]	t	t	t	2026-06-06 21:29:43.352034+05:30	2026-06-22 13:30:17.513844+05:30	You are restricted strictly to Fleet Management topics and user support. If the user asks about or requests access to personal emails, Jira tickets, Telegram messages, or internal infrastructure, you must immediately refuse and rigidly reply: 'I am a customer support assistant. For security reasons, I do not have permission to access or share internal communications or engineering data.'	{"$mode": "whitelist", "page_act": {}, "agent_run": {}, "brain_ask": {}, "page_fill": {}, "page_read": {}, "page_wait": {}, "agent_list": {}, "brain_sync": null, "page_click": {}, "brain_fetch": {}, "brain_stats": {}, "page_select": {}, "query_neo4j": {}, "agent_delete": {}, "brain_search": null, "get_memories": {}, "memory_stats": {}, "memory_store": {}, "page_observe": {}, "memory_forget": {}, "page_navigate": {}, "page_snapshot": {}, "jira_add_comment": {}, "jira_add_worklog": {}, "brain_ingest_file": null, "brain_ingest_text": null, "brain_sync_status": null, "jira_list_tickets": {}, "jira_create_ticket": {}, "jira_update_ticket": {}, "memory_entity_link": {}, "memory_user_context": {}, "memory_company_store": {}, "replace_file_content": {}, "search_elasticsearch": {}, "brain_ingest_directory": null, "jira_transition_ticket": {}, "brain_ingest_current_chat": null}	[]	1. VALID INFORMATION (ALLOW): You must allow all customer-facing support instructions, platform tutorials (e.g., how to add vehicles or drivers), and conversational text to pass through completely unmodified.\n2. INVALID INFORMATION (BLOCK): You must block or redact mentions of Jira, Jira ticket numbers, internal email addresses, Telegram groups, internal tool names, or backend architecture.\n3. SURGICAL REDACTION (BE SMART): If a valid customer support message accidentally includes invalid information (e.g., "Here is how to add a vehicle... I also created Jira ticket SCRUM-123"), you MUST NOT block the entire message. Instead, surgically remove or rewrite ONLY the invalid part (e.g., change it to "... I have forwarded this to our team"), ensuring 100% of the valid support tutorial remains intact for the user.	\N
\.


--
-- Data for Name: code_types; Type: TABLE DATA; Schema: ag_system; Owner: -
--

COPY ag_system.code_types (code_type_id, name, description, created_by, creation_date, updated_by, updation_date) FROM stdin;
1	GenderCD	Gender	\N	2025-03-18 09:38:52.537+05:30	\N	\N
2	RoleCD	Role	\N	2025-03-18 09:38:52.57+05:30	\N	\N
3	ReligionCD	Religion	\N	2025-03-18 09:38:52.61+05:30	\N	\N
4	RelationCD	Relation	\N	2025-03-18 09:38:52.65+05:30	\N	\N
5	CountryCD	Country	\N	2025-03-18 09:38:52.69+05:30	\N	\N
6	StateCD	State	\N	2025-03-18 09:38:52.727+05:30	\N	\N
7	ClassCD	Class	\N	2025-03-18 09:38:52.76+05:30	\N	\N
8	SubjectCD	Subject	\N	2025-03-18 09:38:52.813+05:30	\N	\N
9	HomeworkSubmissionModeCD	Homework Submission Mode	\N	2025-05-23 09:18:55.333+05:30	\N	\N
10	HomeworkStatusCD	Home Wok Status	\N	2025-03-18 09:38:52.123+05:30	\N	\N
11	DayOfWeekCD	Day of Week	\N	2025-03-18 09:38:52.123+05:30	\N	\N
12	QuestionPaperStatusCD	Question Paper Status	\N	2025-03-18 09:38:52.123+05:30	\N	\N
13	AttendenceStatusCD	Attendence Status 	\N	2025-06-03 05:08:59.74+05:30	\N	\N
14	NationalityCD	Nationality	\N	2025-07-13 07:54:26.263+05:30	\N	\N
15	GenreCD	Genre	\N	2025-07-13 09:42:04.523+05:30	\N	\N
16	LibraryBookStatusCD	Library Book Status	\N	2025-07-13 10:45:34.19+05:30	\N	\N
17	LibraryBookConditionCD	Library Book Condition	\N	2025-07-13 10:46:00.953+05:30	\N	\N
18	InventoryCategoryCD	Inventory Category	\N	2025-07-16 08:57:48.04+05:30	\N	\N
22	InventoryUOMCD	Inventory UOM	\N	2025-07-16 09:57:46.607+05:30	\N	\N
23	InventoryConditionCD	Inventory Condition	\N	2025-07-17 12:21:07.247+05:30	\N	\N
29	InventoryTransTypeCD	Transaction Type	\N	2025-07-17 13:04:09.34+05:30	\N	\N
30	TransVehicleTypeCD	Transport Vehicle Type	\N	2025-07-18 13:04:02.47+05:30	\N	\N
31	LeaveStatusCD	Leave Status	\N	2025-07-29 10:14:17.413+05:30	\N	\N
131	PayrollRunStatusCD	Payroll Run Status	\N	2025-08-01 09:06:18.127+05:30	\N	\N
132	PayslipStatusCD	Payslip Status	\N	2025-08-01 09:06:46.153+05:30	\N	\N
133	SalaryComponentTypeCD	Salary Component Type	\N	2025-08-01 09:27:30.76+05:30	\N	\N
134	CalculationTypeCD	Calculation Type	\N	2025-08-01 09:32:06.077+05:30	\N	\N
231	TrainingCourseStatusCD	Training Course Status	\N	2025-08-05 04:23:11.727+05:30	\N	\N
232	ProcessTypesCD	Process Types	\N	2025-08-05 04:36:54.67+05:30	\N	\N
233	ProcessInstanceStatusCD	Process Instance Status	\N	2025-08-05 04:52:03.427+05:30	\N	\N
234	ChecklistStatusCD	Checklist Status	\N	2025-08-05 06:26:50.09+05:30	\N	\N
331	MonthCD	Months	\N	2025-08-17 05:59:27.01+05:30	\N	\N
332	CurrencyCD	Currency	\N	2025-08-19 16:16:15.347+05:30	\N	\N
333	GatewayCD	Gateway	\N	2025-08-19 16:16:27.067+05:30	\N	\N
334	PaymentMethodCD	Payment Method	1	2026-02-23 16:04:54.758098+05:30	\N	\N
335	PaymentStatusCD	Status of payment transactions	1	2026-02-24 12:21:07.309003+05:30	\N	\N
336	InvoiceStatusCD	Status of fee invoices	1	2026-02-24 12:21:07.309003+05:30	\N	\N
337	DiscountTypeCD	Categories of fee discounts	1	2026-02-24 12:21:07.309003+05:30	\N	\N
338	ChargeStatusCD	Status of student fee charges	1	2026-02-24 12:21:07.309003+05:30	\N	\N
339	RefundMethodCD	Methods of fee refunds	1	2026-02-24 12:21:07.309003+05:30	\N	\N
340	WaiverStatusCD	Approval status for fee waivers	1	2026-02-24 12:21:07.309003+05:30	\N	\N
341	MaritalStatusCD	Marital Status	\N	2026-02-28 13:09:33.197399+05:30	\N	\N
342	MotherTongueCD	Mother Tongue	1	2026-02-28 13:15:04.103809+05:30	\N	\N
343	RoomTypeCD	Code data for Room Types	\N	2026-02-28 14:51:47.256374+05:30	\N	\N
50	LeaveStatusCD	Leave Status	1	2026-03-05 13:52:42.731401+05:30	\N	\N
51	AttendanceStatusCD	Attendance Status	1	2026-03-05 13:52:42.731401+05:30	\N	\N
52	ClockEventTypeCD	Clock Event Type	1	2026-03-05 13:52:42.731401+05:30	\N	\N
351	WorkModeCD	Staff Work Mode (Office/WFH/Field)	1	2026-03-05 17:31:51.218022+05:30	\N	\N
352	CorrectionStatusCD	Attendance Correction Status	1	2026-03-05 17:31:51.218022+05:30	\N	\N
353	LLM_PROVIDER	Language Model Providers	0	2026-06-08 09:59:00.062265+05:30	\N	\N
354	LLM_MODEL	Language Models	0	2026-06-08 09:59:00.185652+05:30	\N	\N
355	LLM_BASE_URL	Language Model Base URLs	0	2026-06-08 09:59:00.319957+05:30	\N	\N
\.


--
-- Data for Name: codes; Type: TABLE DATA; Schema: ag_system; Owner: -
--

COPY ag_system.codes (code_id, code_type_id, parent_id, code, weightage, value, english_name, hindi_name, created_by, creation_date, updated_by, updation_date) FROM stdin;
122	8	\N	Science	2	Science	Science	विज्ञान	\N	2025-03-18 09:40:26.727+05:30	\N	\N
123	8	\N	English	3	English	English	अंग्रेज़ी	\N	2025-03-18 09:40:26.773+05:30	\N	\N
124	8	\N	Hindi	4	Hindi	Hindi	हिन्दी	\N	2025-03-18 09:40:26.81+05:30	\N	\N
125	8	\N	SocialStudies	5	Social Studies	Social Studies	सामाजिक अध्ययन	\N	2025-03-18 09:40:26.847+05:30	\N	\N
126	8	\N	Physics	6	Physics	Physics	भौतिकी	\N	2025-03-18 09:40:26.883+05:30	\N	\N
127	8	\N	Chemistry	7	Chemistry	Chemistry	रसायन विज्ञान	\N	2025-03-18 09:40:26.917+05:30	\N	\N
128	8	\N	Biology	8	Biology	Biology	जीवविज्ञान	\N	2025-03-18 09:40:26.953+05:30	\N	\N
129	8	\N	History	9	History	History	इतिहास	\N	2025-03-18 09:40:26.99+05:30	\N	\N
130	8	\N	Geography	10	Geography	Geography	भूगोल	\N	2025-03-18 09:40:27.023+05:30	\N	\N
131	9	\N	ONLINE	1	Submitted Online	Online	ऑनलाइन	\N	2025-05-23 09:25:43.913+05:30	\N	\N
132	9	\N	PAPER	2	Submitted on Paper	Paper	कागज़	\N	2025-05-23 09:25:43.913+05:30	\N	\N
133	10	\N	PENDING	1	Not yet done	Pending	लंबित	\N	2025-05-23 09:25:43.913+05:30	\N	\N
134	10	\N	COMPLETED	2	Work completed	Completed	पूर्ण	\N	2025-05-23 09:25:43.913+05:30	\N	\N
135	11	\N	SUN	1	Sunday	Sunday	रविवार	1	2025-05-26 05:54:59.243+05:30	1	2025-05-26 05:54:59.243+05:30
136	11	\N	MON	2	Monday	Monday	सोमवार	1	2025-05-26 05:54:59.243+05:30	1	2025-05-26 05:54:59.243+05:30
137	11	\N	TUE	3	Tuesday	Tuesday	मंगलवार	1	2025-05-26 05:54:59.243+05:30	1	2025-05-26 05:54:59.243+05:30
138	11	\N	WED	4	Wednesday	Wednesday	बुधवार	1	2025-05-26 05:54:59.243+05:30	1	2025-05-26 05:54:59.243+05:30
139	11	\N	THU	5	Thursday	Thursday	गुरुवार	1	2025-05-26 05:54:59.243+05:30	1	2025-05-26 05:54:59.243+05:30
140	11	\N	FRI	6	Friday	Friday	शुक्रवार	1	2025-05-26 05:54:59.243+05:30	1	2025-05-26 05:54:59.243+05:30
141	11	\N	SAT	7	Saturday	Saturday	शनिवार	1	2025-05-26 05:54:59.243+05:30	1	2025-05-26 05:54:59.243+05:30
143	12	\N	DRAFT	1	Draft	Draft	ड्राफ्ट	1	2025-05-26 09:50:40.377+05:30	\N	\N
144	12	\N	PENDING	2	Pending Approval	Pending Approval	अनुमोदन लंबित	1	2025-05-26 09:50:40.377+05:30	\N	\N
145	12	\N	APPROVED	3	Approved	Approved	अनुमोदित	1	2025-05-26 09:50:40.377+05:30	\N	\N
146	12	\N	REJECTED	4	Rejected	Rejected	अस्वीकृत	1	2025-05-26 09:50:40.377+05:30	\N	\N
147	12	\N	PUBLISHED	5	Published	Published	प्रकाशित	1	2025-05-26 09:50:40.377+05:30	\N	\N
148	13	\N	Present	1	1	Present	उपस्थित	1	2025-06-03 05:11:26.337+05:30	1	2025-06-03 05:11:26.337+05:30
149	13	\N	Absent	2	2	Absent	अनुपस्थित	1	2025-06-03 05:11:26.343+05:30	1	2025-06-03 05:11:26.343+05:30
150	13	\N	Leave	3	3	Leave	अवकाश	1	2025-06-03 05:11:26.35+05:30	1	2025-06-03 05:11:26.35+05:30
151	13	\N	Not Marked	4	0	Not Marked	चिह्नित नहीं	1	2025-06-03 05:11:26.36+05:30	1	2025-06-03 05:11:26.36+05:30
152	14	\N	IN	1	Indian	Indian	भारतीय	1	2025-07-13 07:55:58.017+05:30	1	2025-07-13 07:55:58.017+05:30
153	14	\N	US	2	American	American	अमेरिकी	1	2025-07-13 07:55:58.017+05:30	1	2025-07-13 07:55:58.017+05:30
154	14	\N	UK	3	British	British	ब्रिटिश	1	2025-07-13 07:55:58.017+05:30	1	2025-07-13 07:55:58.017+05:30
155	14	\N	CA	4	Canadian	Canadian	कनाडाई	1	2025-07-13 07:55:58.017+05:30	1	2025-07-13 07:55:58.017+05:30
156	14	\N	AU	5	Australian	Australian	ऑस्ट्रेलियाई	1	2025-07-13 07:55:58.017+05:30	1	2025-07-13 07:55:58.017+05:30
157	14	\N	CN	6	Chinese	Chinese	चीनी	1	2025-07-13 07:55:58.017+05:30	1	2025-07-13 07:55:58.017+05:30
158	14	\N	FR	7	French	French	फ्रांसीसी	1	2025-07-13 07:55:58.017+05:30	1	2025-07-13 07:55:58.017+05:30
159	14	\N	DE	8	German	German	जर्मन	1	2025-07-13 07:55:58.017+05:30	1	2025-07-13 07:55:58.017+05:30
160	14	\N	JP	9	Japanese	Japanese	जापानी	1	2025-07-13 07:55:58.017+05:30	1	2025-07-13 07:55:58.017+05:30
161	14	\N	RU	10	Russian	Russian	रूसी	1	2025-07-13 07:55:58.017+05:30	1	2025-07-13 07:55:58.017+05:30
162	15	\N	SCI	1	Science	Science	विज्ञान	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
163	15	\N	MATH	2	Mathematics	Mathematics	गणित	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
164	15	\N	HIN	3	Hindi	Hindi	हिन्दी	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
165	15	\N	ENG	4	English	English	अंग्रेज़ी	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
166	15	\N	SST	5	Social Studies	Social Studies	सामाजिक अध्ययन	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
167	15	\N	POL	6	Political Science	Political Science	राजनीति विज्ञान	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
168	15	\N	BIO	7	Biology	Biology	जीव विज्ञान	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
169	15	\N	PHY	8	Physics	Physics	भौतिकी	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
170	15	\N	CHE	9	Chemistry	Chemistry	रसायन विज्ञान	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
171	15	\N	CS	10	Computer Science	Computer Science	कंप्यूटर विज्ञान	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
172	15	\N	COM	11	Commerce	Commerce	वाणिज्य	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
173	15	\N	ECO	12	Economics	Economics	अर्थशास्त्र	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
174	15	\N	GK	13	General Knowledge	General Knowledge	सामान्य ज्ञान	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
175	15	\N	REF	14	Reference	Reference	संदर्भ सामग्री	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
176	15	\N	STORY	15	Story Books	Story Books	कथा पुस्तकें	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
177	15	\N	MAG	16	Magazines	Magazines	पत्रिकाएँ	1	2025-07-13 09:45:44.383+05:30	1	2025-07-13 09:45:44.383+05:30
178	16	\N	Available	1	Available	Available	उपलब्ध	1	2025-07-13 10:47:51.153+05:30	1	2025-07-13 10:47:51.153+05:30
179	16	\N	Loaned	2	Loaned	Loaned	उधार	1	2025-07-13 10:47:51.153+05:30	1	2025-07-13 10:47:51.153+05:30
180	16	\N	Reserved	3	Reserved	Reserved	आरक्षित	1	2025-07-13 10:47:51.153+05:30	1	2025-07-13 10:47:51.153+05:30
181	16	\N	Lost	4	Lost	Lost	गुम	1	2025-07-13 10:47:51.153+05:30	1	2025-07-13 10:47:51.153+05:30
182	16	\N	Damaged	5	Damaged	Damaged	क्षतिग्रस्त	1	2025-07-13 10:47:51.153+05:30	1	2025-07-13 10:47:51.153+05:30
183	16	\N	Under Repair	6	Under Repair	Under Repair	मरम्मताधीन	1	2025-07-13 10:47:51.153+05:30	1	2025-07-13 10:47:51.153+05:30
184	16	\N	Archived	7	Archived	Archived	पुरालेखित	1	2025-07-13 10:47:51.153+05:30	1	2025-07-13 10:47:51.153+05:30
239	23	\N	NEEDS_MAINTENANCE	7	\N	Needs Maintenance	रखरखाव की आवश्यकता	1	2025-07-17 12:22:52.73+05:30	\N	\N
240	23	\N	DAMAGED_MINOR	8	\N	Damaged (Minor)	मामूली क्षतिग्रस्त	1	2025-07-17 12:22:52.73+05:30	\N	\N
241	23	\N	DAMAGED_MAJOR	9	\N	Damaged (Major)	बड़ी क्षति	1	2025-07-17 12:22:52.73+05:30	\N	\N
242	23	\N	UNDER_REPAIR	10	\N	Under Repair	मरम्मत के अधीन	1	2025-07-17 12:22:52.73+05:30	\N	\N
243	23	\N	REPAIRED	11	\N	Repaired	मरम्मत किया गया	1	2025-07-17 12:22:52.73+05:30	\N	\N
185	16	\N	Disposed	8	Disposed	Disposed	नष्ट	1	2025-07-13 10:47:51.153+05:30	1	2025-07-13 10:47:51.153+05:30
186	17	\N	New	1	New	New	नई स्थिति	1	2025-07-13 10:47:51.303+05:30	1	2025-07-13 10:47:51.303+05:30
187	17	\N	Good	2	Good	Good	अच्छी स्थिति	1	2025-07-13 10:47:51.303+05:30	1	2025-07-13 10:47:51.303+05:30
188	17	\N	Fair	3	Fair	Fair	संतोषजनक स्थिति	1	2025-07-13 10:47:51.303+05:30	1	2025-07-13 10:47:51.303+05:30
189	17	\N	Poor	4	Poor	Poor	खराब स्थिति	1	2025-07-13 10:47:51.303+05:30	1	2025-07-13 10:47:51.303+05:30
190	17	\N	Damaged	5	Damaged	Damaged	क्षतिग्रस्त	1	2025-07-13 10:47:51.303+05:30	1	2025-07-13 10:47:51.303+05:30
191	17	\N	Needs Repair	6	Needs Repair	Needs Repair	मरम्मत आवश्यक	1	2025-07-13 10:47:51.303+05:30	1	2025-07-13 10:47:51.303+05:30
192	17	\N	Repaired	7	Repaired	Repaired	मरम्मत की गई	1	2025-07-13 10:47:51.303+05:30	1	2025-07-13 10:47:51.303+05:30
193	18	0	STATIONERY	1	Stationery	Stationery	स्टेशनरी	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
194	18	0	FURNITURE	2	Furniture	Furniture	फर्नीचर	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
1	1	\N	MALE	\N	MALE	MALE	पुरुष	\N	2025-03-18 09:40:23.677+05:30	\N	\N
2	1	\N	FEMALE	\N	FEMALE	FEMALE	महिला	\N	2025-03-18 09:40:23.72+05:30	\N	\N
3	1	\N	OTHER	\N	OTHER	OTHER	अन्य	\N	2025-03-18 09:40:23.76+05:30	\N	\N
4	2	\N	SYSTEM-ADMIN	\N	SYSTEM ADMIN	SYSTEM ADMIN	सिस्टम एडमिन	\N	2025-03-18 09:40:23.79+05:30	\N	\N
5	2	\N	PRINCIPAL	\N	PRINCIPAL	PRINCIPAL	प्रधानाचार्य	\N	2025-03-18 09:40:23.82+05:30	\N	\N
6	2	\N	TEACHER	\N	TEACHER	TEACHER	अध्यापक	\N	2025-03-18 09:40:23.853+05:30	\N	\N
7	2	\N	DRIVER	\N	DRIVER	DRIVER	ड्राइवर	\N	2025-03-18 09:40:23.883+05:30	\N	\N
8	2	\N	OTHER-STAFF	\N	OTHER STAFF	OTHER STAFF	अन्य कर्मचारी	\N	2025-03-18 09:40:23.913+05:30	\N	\N
40	3	\N	HINDUISM	\N	HINDUISM	HINDUISM	हिंदू	\N	2025-03-18 09:40:23.947+05:30	\N	\N
41	3	\N	ISLAM	\N	ISLAM	ISLAM	इस्लाम	\N	2025-03-18 09:40:23.977+05:30	\N	\N
42	3	\N	CHRISTIANITY	\N	CHRISTIANITY	CHRISTIANITY	ईसाई	\N	2025-03-18 09:40:24.013+05:30	\N	\N
43	3	\N	SIKHISM	\N	SIKHISM	SIKHISM	सिख	\N	2025-03-18 09:40:24.047+05:30	\N	\N
44	3	\N	BUDDHISM	\N	BUDDHISM	BUDDHISM	बौद्ध	\N	2025-03-18 09:40:24.077+05:30	\N	\N
45	3	\N	JAINISM	\N	JAINISM	JAINISM	जैन	\N	2025-03-18 09:40:24.11+05:30	\N	\N
46	3	\N	ZOROASTRIANISM	\N	ZOROASTRIANISM	ZOROASTRIANISM	पारसी	\N	2025-03-18 09:40:24.143+05:30	\N	\N
47	3	\N	JUDAISM	\N	JUDAISM	JUDAISM	यहूदी	\N	2025-03-18 09:40:24.177+05:30	\N	\N
48	4	\N	FATHER	\N	Father	FATHER	पिता	\N	2025-03-18 09:40:24.21+05:30	\N	\N
49	4	\N	MOTHER	\N	Mother	MOTHER	माता	\N	2025-03-18 09:40:24.24+05:30	\N	\N
50	4	\N	SON	\N	Son	SON	पुत्र	\N	2025-03-18 09:40:24.27+05:30	\N	\N
51	4	\N	DAUGHTER	\N	Daughter	DAUGHTER	पुत्री	\N	2025-03-18 09:40:24.3+05:30	\N	\N
52	4	\N	BROTHER	\N	Brother	BROTHER	भाई	\N	2025-03-18 09:40:24.333+05:30	\N	\N
53	4	\N	SISTER	\N	Sister	SISTER	बहन	\N	2025-03-18 09:40:24.367+05:30	\N	\N
54	4	\N	HUSBAND	\N	Husband	HUSBAND	पति	\N	2025-03-18 09:40:24.397+05:30	\N	\N
55	4	\N	WIFE	\N	Wife	WIFE	पत्नी	\N	2025-03-18 09:40:24.433+05:30	\N	\N
56	4	\N	GRANDFATHER	\N	Grandfather	GRANDFATHER	दादा / नाना	\N	2025-03-18 09:40:24.463+05:30	\N	\N
57	4	\N	GRANDMOTHER	\N	Grandmother	GRANDMOTHER	दादी / नानी	\N	2025-03-18 09:40:24.497+05:30	\N	\N
58	4	\N	UNCLE	\N	Uncle	UNCLE	चाचा / मामा	\N	2025-03-18 09:40:24.527+05:30	\N	\N
59	4	\N	AUNT	\N	Aunt	AUNT	चाची / मामी	\N	2025-03-18 09:40:24.557+05:30	\N	\N
60	4	\N	COUSIN	\N	Cousin	COUSIN	चचेरा भाई / चचेरी बहन	\N	2025-03-18 09:40:24.587+05:30	\N	\N
61	4	\N	NEPHEW	\N	Nephew	NEPHEW	भतीजा / भांजा	\N	2025-03-18 09:40:24.62+05:30	\N	\N
62	4	\N	NIECE	\N	Niece	NIECE	भतीजी / भांजी	\N	2025-03-18 09:40:24.653+05:30	\N	\N
63	4	\N	SON-IN-LAW	\N	Son in law	SON-IN-LAW	दामाद	\N	2025-03-18 09:40:24.687+05:30	\N	\N
64	4	\N	DAUGHTER-IN-LAW	\N	Daughter in law	DAUGHTER IN LAW	बहू	\N	2025-03-18 09:40:24.73+05:30	\N	\N
65	4	\N	FATHER-IN-LAW	\N	Father in law	FATHER IN LAW	ससुर	\N	2025-03-18 09:40:24.767+05:30	\N	\N
66	4	\N	MOTHER-IN-LAW	\N	Mother in law	MOTHER IN LAW	सास	\N	2025-03-18 09:40:24.8+05:30	\N	\N
67	4	\N	BROTHER-IN-LAW	\N	Brother in law	BROTHER IN LAW	देवर / साला	\N	2025-03-18 09:40:24.833+05:30	\N	\N
68	4	\N	SISTER-IN-LAW	\N	Sister in law	SISTER IN LAW	ननद / सालहज	\N	2025-03-18 09:40:24.873+05:30	\N	\N
69	4	\N	GRANDSON	\N	Grandson	GRANDSON	पोता / नाती	\N	2025-03-18 09:40:24.907+05:30	\N	\N
70	4	\N	GRANDDAUGHTER	\N	Granddaughter	GRAND DAUGHTER	पोती / नातिन	\N	2025-03-18 09:40:24.947+05:30	\N	\N
72	5	\N	INDIA	\N	India	India	भारत	\N	2025-03-18 09:40:24.98+05:30	\N	\N
73	6	72	Andhra_Pradesh	\N	Andhra Pradesh	Andhra Pradesh	आंध्र प्रदेश	\N	2025-03-18 09:40:25.017+05:30	\N	\N
74	6	72	Arunachal_Pradesh	\N	Arunachal Pradesh	Arunachal Pradesh	अरुणाचल प्रदेश	\N	2025-03-18 09:40:25.05+05:30	\N	\N
75	6	72	Assam	\N	Assam	Assam	असम	\N	2025-03-18 09:40:25.09+05:30	\N	\N
76	6	72	Bihar	\N	Bihar	Bihar	बिहार	\N	2025-03-18 09:40:25.12+05:30	\N	\N
77	6	72	Chhattisgarh	\N	Chhattisgarh	Chhattisgarh	छत्तीसगढ़	\N	2025-03-18 09:40:25.157+05:30	\N	\N
78	6	72	Goa	\N	Goa	Goa	गोवा	\N	2025-03-18 09:40:25.2+05:30	\N	\N
79	6	72	Gujarat	\N	Gujarat	Gujarat	गुजरात	\N	2025-03-18 09:40:25.233+05:30	\N	\N
80	6	72	Haryana	\N	Haryana	Haryana	हरियाणा	\N	2025-03-18 09:40:25.267+05:30	\N	\N
81	6	72	Himachal_Pradesh	\N	Himachal Pradesh	Himachal Pradesh	हिमाचल प्रदेश	\N	2025-03-18 09:40:25.31+05:30	\N	\N
82	6	72	Jharkhand	\N	Jharkhand	Jharkhand	झारखंड	\N	2025-03-18 09:40:25.35+05:30	\N	\N
83	6	72	Karnataka	\N	Karnataka	Karnataka	कर्नाटक	\N	2025-03-18 09:40:25.38+05:30	\N	\N
84	6	72	Kerala	\N	Kerala	Kerala	केरल	\N	2025-03-18 09:40:25.41+05:30	\N	\N
85	6	72	Madhya_Pradesh	\N	Madhya Pradesh	Madhya Pradesh	मध्य प्रदेश	\N	2025-03-18 09:40:25.44+05:30	\N	\N
86	6	72	Maharashtra	\N	Maharashtra	Maharashtra	महाराष्ट्र	\N	2025-03-18 09:40:25.473+05:30	\N	\N
87	6	72	Manipur	\N	Manipur	Manipur	मणिपुर	\N	2025-03-18 09:40:25.503+05:30	\N	\N
88	6	72	Meghalaya	\N	Meghalaya	Meghalaya	मेघालय	\N	2025-03-18 09:40:25.537+05:30	\N	\N
89	6	72	Mizoram	\N	Mizoram	Mizoram	मिजोरम	\N	2025-03-18 09:40:25.57+05:30	\N	\N
90	6	72	Nagaland	\N	Nagaland	Nagaland	नागालैंड	\N	2025-03-18 09:40:25.603+05:30	\N	\N
91	6	72	Odisha	\N	Odisha	Odisha	ओडिशा	\N	2025-03-18 09:40:25.633+05:30	\N	\N
92	6	72	Punjab	\N	Punjab	Punjab	पंजाब	\N	2025-03-18 09:40:25.673+05:30	\N	\N
93	6	72	Rajasthan	\N	Rajasthan	Rajasthan	राजस्थान	\N	2025-03-18 09:40:25.703+05:30	\N	\N
94	6	72	Sikkim	\N	Sikkim	Sikkim	सिक्किम	\N	2025-03-18 09:40:25.747+05:30	\N	\N
95	6	72	Tamil_Nadu	\N	Tamil Nadu	Tamil Nadu	तमिलनाडु	\N	2025-03-18 09:40:25.78+05:30	\N	\N
96	6	72	Telangana	\N	Telangana	Telangana	तेलंगाना	\N	2025-03-18 09:40:25.813+05:30	\N	\N
97	6	72	Tripura	\N	Tripura	Tripura	त्रिपुरा	\N	2025-03-18 09:40:25.843+05:30	\N	\N
98	6	72	Uttar_Pradesh	\N	Uttar Pradesh	Uttar Pradesh	उत्तर प्रदेश	\N	2025-03-18 09:40:25.873+05:30	\N	\N
4336	353	\N	google	\N	\N	Google	\N	0	2026-06-19 03:53:59.453472+05:30	\N	\N
99	6	72	Uttarakhand	\N	Uttarakhand	Uttarakhand	उत्तराखंड	\N	2025-03-18 09:40:25.907+05:30	\N	\N
100	6	72	West_Bengal	\N	West Bengal	West Bengal	पश्चिम बंगाल	\N	2025-03-18 09:40:25.94+05:30	\N	\N
101	6	72	Andaman_and_Nicobar_Islands	\N	Andaman and Nicobar Islands	Andaman and Nicobar Islands	अंडमान और निकोबार द्वीप समूह	\N	2025-03-18 09:40:25.977+05:30	\N	\N
102	6	72	Chandigarh	\N	Chandigarh	Chandigarh	चंडीगढ़	\N	2025-03-18 09:40:26.01+05:30	\N	\N
103	6	72	Dadra_and_Nagar_Haveli_and_Daman_and_Diu	\N	Dadra and Nagar Haveli and Daman and Diu	Dadra and Nagar Haveli and Daman and Diu	दादरा और नगर हवेली और दमन और दीव	\N	2025-03-18 09:40:26.06+05:30	\N	\N
104	6	72	Delhi	\N	Delhi	Delhi	दिल्ली	\N	2025-03-18 09:40:26.097+05:30	\N	\N
105	6	72	Jammu_and_Kashmir	\N	Jammu and Kashmir	Jammu and Kashmir	जम्मू और कश्मीर	\N	2025-03-18 09:40:26.127+05:30	\N	\N
106	6	72	Ladakh	\N	Ladakh	Ladakh	लद्दाख	\N	2025-03-18 09:40:26.163+05:30	\N	\N
107	6	72	Lakshadweep	\N	Lakshadweep	Lakshadweep	लक्षद्वीप	\N	2025-03-18 09:40:26.197+05:30	\N	\N
108	6	72	Puducherry	\N	Puducherry	Puducherry	पुदुचेरी	\N	2025-03-18 09:40:26.23+05:30	\N	\N
121	8	\N	Math	1	Mathematics	Mathematics	गणित	\N	2025-03-18 09:40:26.69+05:30	\N	\N
195	18	0	IT_EQUIP	3	IT Equipment	IT Equipment	आईटी उपकरण	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
196	18	0	SPORTS	4	Sports Equipment	Sports Equipment	खेल उपकरण	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
197	18	0	LAB_EQUIP	5	Lab Equipment	Lab Equipment	प्रयोगशाला उपकरण	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
198	18	0	CLEANING	6	Cleaning Supplies	Cleaning Supplies	सफाई सामग्री	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
199	18	0	LIBRARY	7	Library Books	Library Books	पुस्तकालय पुस्तकें	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
200	18	0	ART_CRAFT	8	Art & Craft Supplies	Art & Craft Supplies	कला और शिल्प सामग्री	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
201	18	0	UNIFORMS	9	Uniforms & Badges	Uniforms & Badges	यूनिफॉर्म और बैज	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
202	18	0	MISC	10	Miscellaneous	Miscellaneous	विविध	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
203	18	0	KITCHEN	11	Kitchen Equipment	Kitchen Equipment	रसोई उपकरण	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
204	18	0	MEDICAL	12	Medical Supplies	Medical Supplies	चिकित्सा सामग्री	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
205	18	0	ELECTRICAL	13	Electrical Items	Electrical Items	विद्युत सामग्री	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
206	18	0	MAINTENANCE	14	Maintenance Tools	Maintenance Tools	रखरखाव उपकरण	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
207	18	0	VEHICLES	15	Transport Vehicles	Transport Vehicles	वाहन	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
208	18	0	HOSTEL	16	Hostel Items	Hostel Items	हॉस्टल सामग्री	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
209	18	0	AUDIO_VISUAL	17	Audio Visual Equip	Audio Visual Equip	ऑडियो विजुअल उपकरण	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
210	18	0	EXAM	18	Exam Materials	Exam Materials	परीक्षा सामग्री	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
211	18	0	LAB_UNIFORMS	19	Lab Uniforms	Lab Uniforms	प्रयोगशाला यूनिफॉर्म	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
212	18	0	GARDEN	20	Gardening Tools	Gardening Tools	बागवानी उपकरण	1	2025-07-16 09:00:48.453+05:30	1	2025-07-16 09:00:48.453+05:30
213	22	\N	Piece	1	Piece	Piece	नग	1	2025-07-16 10:00:45.28+05:30	1	2025-07-16 10:00:45.28+05:30
214	22	\N	Box	2	Box	Box	बॉक्स	1	2025-07-16 10:00:45.28+05:30	1	2025-07-16 10:00:45.28+05:30
215	22	\N	Packet	3	Packet	Packet	पैकेट	1	2025-07-16 10:00:45.28+05:30	1	2025-07-16 10:00:45.28+05:30
216	22	\N	Liter	4	Liter	Liter	लीटर	1	2025-07-16 10:00:45.28+05:30	1	2025-07-16 10:00:45.28+05:30
217	22	\N	Kilogram	5	Kilogram	Kilogram	किलोग्राम	1	2025-07-16 10:00:45.28+05:30	1	2025-07-16 10:00:45.28+05:30
218	22	\N	Meter	6	Meter	Meter	मीटर	1	2025-07-16 10:00:45.28+05:30	1	2025-07-16 10:00:45.28+05:30
219	22	\N	Set	7	Set	Set	सेट	1	2025-07-16 10:00:45.28+05:30	1	2025-07-16 10:00:45.28+05:30
220	22	\N	Bundle	8	Bundle	Bundle	बंडल	1	2025-07-16 10:00:45.28+05:30	1	2025-07-16 10:00:45.28+05:30
221	22	\N	Roll	9	Roll	Roll	रोल	1	2025-07-16 10:00:45.28+05:30	1	2025-07-16 10:00:45.28+05:30
222	22	\N	Bottle	10	Bottle	Bottle	बोतल	1	2025-07-16 10:00:45.28+05:30	1	2025-07-16 10:00:45.28+05:30
223	22	\N	Gram	11	Gram	Gram	ग्राम	1	2025-07-16 10:00:48.663+05:30	1	2025-07-16 10:00:48.663+05:30
224	22	\N	Dozen	12	Dozen	Dozen	दर्जन	1	2025-07-16 10:00:48.663+05:30	1	2025-07-16 10:00:48.663+05:30
225	22	\N	Pair	13	Pair	Pair	जोड़ी	1	2025-07-16 10:00:48.663+05:30	1	2025-07-16 10:00:48.663+05:30
226	22	\N	Pack	14	Pack	Pack	पैक	1	2025-07-16 10:00:48.663+05:30	1	2025-07-16 10:00:48.663+05:30
227	22	\N	Sheet	15	Sheet	Sheet	शीट	1	2025-07-16 10:00:48.663+05:30	1	2025-07-16 10:00:48.663+05:30
228	22	\N	Jar	16	Jar	Jar	जार	1	2025-07-16 10:00:48.663+05:30	1	2025-07-16 10:00:48.663+05:30
229	22	\N	Tube	17	Tube	Tube	ट्यूब	1	2025-07-16 10:00:48.663+05:30	1	2025-07-16 10:00:48.663+05:30
230	22	\N	Can	18	Can	Can	कैन	1	2025-07-16 10:00:48.663+05:30	1	2025-07-16 10:00:48.663+05:30
231	22	\N	Box Set	19	Box Set	Box Set	बॉक्स सेट	1	2025-07-16 10:00:48.663+05:30	1	2025-07-16 10:00:48.663+05:30
232	22	\N	Carton	20	Carton	Carton	कार्टन	1	2025-07-16 10:00:48.663+05:30	1	2025-07-16 10:00:48.663+05:30
233	23	\N	NEW	1	\N	New	नया	1	2025-07-17 12:22:52.73+05:30	\N	\N
234	23	\N	EXCELLENT	2	\N	Excellent	उत्कृष्ट	1	2025-07-17 12:22:52.73+05:30	\N	\N
235	23	\N	GOOD	3	\N	Good	अच्छा	1	2025-07-17 12:22:52.73+05:30	\N	\N
236	23	\N	FAIR	4	\N	Fair	ठीक-ठाक	1	2025-07-17 12:22:52.73+05:30	\N	\N
237	23	\N	AVERAGE	5	\N	Average	औसत	1	2025-07-17 12:22:52.73+05:30	\N	\N
238	23	\N	WORN_OUT	6	\N	Worn Out	घिसा हुआ	1	2025-07-17 12:22:52.73+05:30	\N	\N
244	23	\N	OBSOLETE	12	\N	Obsolete	अप्रचलित	1	2025-07-17 12:22:52.73+05:30	\N	\N
245	23	\N	RETIRED	13	\N	Retired	सेवामुक्त	1	2025-07-17 12:22:52.73+05:30	\N	\N
246	23	\N	LOST	14	\N	Lost	खो गया	1	2025-07-17 12:22:52.73+05:30	\N	\N
247	23	\N	STOLEN	15	\N	Stolen	चोरी हो गया	1	2025-07-17 12:22:52.73+05:30	\N	\N
248	23	\N	RETURNED	16	\N	Returned	वापस किया गया	1	2025-07-17 12:22:52.73+05:30	\N	\N
249	23	\N	REPLACED	17	\N	Replaced	बदल दिया गया	1	2025-07-17 12:22:52.73+05:30	\N	\N
250	23	\N	EXPIRED	18	\N	Expired	समाप्त	1	2025-07-17 12:22:52.73+05:30	\N	\N
251	23	\N	REISSUED	19	\N	Reissued	पुनः जारी किया गया	1	2025-07-17 12:22:52.73+05:30	\N	\N
252	23	\N	IN_STORAGE	20	\N	In Storage	भंडारण में	1	2025-07-17 12:22:52.73+05:30	\N	\N
253	29	\N	ISSUE	1	Issue	Issue to Staff/Department	स्टाफ/विभाग को निर्गम	1	2025-07-17 13:07:25.227+05:30	1	2025-07-17 13:07:25.227+05:30
254	29	\N	RETURN	2	Return	Return from Staff	स्टाफ से वापसी	1	2025-07-17 13:07:25.227+05:30	1	2025-07-17 13:07:25.227+05:30
255	29	\N	TRANSFER	3	Transfer	Transfer between Locations	स्थानों के बीच स्थानांतरण	1	2025-07-17 13:07:25.227+05:30	1	2025-07-17 13:07:25.227+05:30
256	29	\N	DAMAGE	4	Damage	Mark as Damaged	क्षतिग्रस्त चिह्नित करें	1	2025-07-17 13:07:25.227+05:30	1	2025-07-17 13:07:25.227+05:30
257	29	\N	LOST	5	Lost	Mark as Lost	खोया हुआ चिह्नित करें	1	2025-07-17 13:07:25.227+05:30	1	2025-07-17 13:07:25.227+05:30
258	29	\N	PURCHASE	6	Purchase	Purchased Stock	खरीदी गई सामग्री	1	2025-07-17 13:07:25.227+05:30	1	2025-07-17 13:07:25.227+05:30
259	29	\N	ADJUST	7	Adjustment	Stock Adjustment	स्टॉक समायोजन	1	2025-07-17 13:07:25.227+05:30	1	2025-07-17 13:07:25.227+05:30
260	29	\N	DONATION	8	Donation	Donated Stock	दान की गई सामग्री	1	2025-07-17 13:07:25.227+05:30	1	2025-07-17 13:07:25.227+05:30
261	30	\N	bus	1	Bus	Bus	बस	1	2025-07-18 13:06:23.437+05:30	1	2025-07-18 13:06:23.437+05:30
262	30	\N	van	2	Van	Van	वैन	1	2025-07-18 13:06:23.437+05:30	1	2025-07-18 13:06:23.437+05:30
263	30	\N	auto	3	Auto	Auto	ऑटो	1	2025-07-18 13:06:23.437+05:30	1	2025-07-18 13:06:23.437+05:30
264	30	\N	car	4	Car	Car	कार	1	2025-07-18 13:06:23.437+05:30	1	2025-07-18 13:06:23.437+05:30
265	30	\N	minibus	5	Mini Bus	Mini Bus	मिनी बस	1	2025-07-18 13:06:23.437+05:30	1	2025-07-18 13:06:23.437+05:30
266	31	\N	APPROVED	1	Approved	Approved	स्वीकृत	1	2025-07-29 10:16:29.393+05:30	1	2025-07-29 10:16:29.393+05:30
267	31	\N	PENDING	1	Pending	Pending	लंबित	1	2025-07-29 10:16:29.477+05:30	1	2025-07-29 10:16:29.477+05:30
268	31	\N	REJECTED	2	Rejected	Rejected	अस्वीकृत	1	2025-07-29 10:16:29.477+05:30	1	2025-07-29 10:16:29.477+05:30
366	131	\N	DRAFT	1	Draft	Draft	ड्राफ्ट	1	2025-08-01 09:08:33.69+05:30	1	2025-08-01 09:08:33.69+05:30
367	131	\N	PROCESSING	2	Processing	Processing	प्रोसेसिंग	1	2025-08-01 09:08:33.69+05:30	1	2025-08-01 09:08:33.69+05:30
368	131	\N	APPROVED	3	Approved	Approved	स्वीकृत	1	2025-08-01 09:08:33.69+05:30	1	2025-08-01 09:08:33.69+05:30
369	131	\N	REJECTED	4	Rejected	Rejected	अस्वीकृत	1	2025-08-01 09:08:33.69+05:30	1	2025-08-01 09:08:33.69+05:30
370	132	\N	PENDING	1	Pending	Pending	विचाराधीन	1	2025-08-01 09:08:33.693+05:30	1	2025-08-01 09:08:33.693+05:30
371	132	\N	GENERATED	2	Generated	Generated	निर्मित	1	2025-08-01 09:08:33.693+05:30	1	2025-08-01 09:08:33.693+05:30
372	132	\N	DISTRIBUTED	3	Distributed	Distributed	वितरित	1	2025-08-01 09:08:33.693+05:30	1	2025-08-01 09:08:33.693+05:30
373	132	\N	CANCELLED	4	Cancelled	Cancelled	रद्द	1	2025-08-01 09:08:33.693+05:30	1	2025-08-01 09:08:33.693+05:30
374	133	\N	EARNING	1	Earning	Earning	आय	1	2025-08-01 09:28:40.087+05:30	1	2025-08-01 09:28:40.087+05:30
375	133	\N	DEDUCTION	2	Deduction	Deduction	कटौती	1	2025-08-01 09:28:40.087+05:30	1	2025-08-01 09:28:40.087+05:30
376	133	\N	BONUS	3	Bonus	Bonus	बोनस	1	2025-08-01 09:28:40.087+05:30	1	2025-08-01 09:28:40.087+05:30
377	133	\N	REIMBURSEMENT	4	Reimbursement	Reimbursement	प्रतिपूर्ति	1	2025-08-01 09:28:40.087+05:30	1	2025-08-01 09:28:40.087+05:30
378	133	\N	ALLOWANCE	5	Allowance	Allowance	भत्ता	1	2025-08-01 09:28:40.087+05:30	1	2025-08-01 09:28:40.087+05:30
379	133	\N	INCENTIVE	6	Incentive	Incentive	प्रोत्साहन	1	2025-08-01 09:28:40.087+05:30	1	2025-08-01 09:28:40.087+05:30
380	134	\N	FIXED	1	Fixed	Fixed	निश्चित	1	2025-08-01 09:32:53.823+05:30	1	2025-08-01 09:32:53.823+05:30
381	134	\N	PERCENTAGE	2	Percentage	Percentage	प्रतिशत	1	2025-08-01 09:32:53.823+05:30	1	2025-08-01 09:32:53.823+05:30
382	134	\N	FORMULA	3	Formula	Formula	सूत्र	1	2025-08-01 09:32:53.823+05:30	1	2025-08-01 09:32:53.823+05:30
466	231	\N	PLN	1	Planned	Planned	योजना बनाई गई	1	2025-08-05 04:25:05.41+05:30	1	2025-08-05 04:25:05.41+05:30
467	231	\N	ONG	2	Ongoing	Ongoing	चालू	1	2025-08-05 04:25:05.41+05:30	1	2025-08-05 04:25:05.41+05:30
468	231	\N	COM	3	Completed	Completed	पूर्ण	1	2025-08-05 04:25:05.41+05:30	1	2025-08-05 04:25:05.41+05:30
469	231	\N	CAN	4	Cancelled	Cancelled	रद्द किया गया	1	2025-08-05 04:25:05.41+05:30	1	2025-08-05 04:25:05.41+05:30
470	232	\N	VERIFY	6	Document Verification	Document Verification	दस्तावेज़ सत्यापन	1	2025-08-05 04:41:22.693+05:30	1	2025-08-05 04:41:22.693+05:30
471	232	\N	BGCHK	7	Background Check	Background Check	पृष्ठभूमि जांच	1	2025-08-05 04:41:22.693+05:30	1	2025-08-05 04:41:22.693+05:30
472	232	\N	ORIENT	8	Orientation	Orientation	अभिविन्यास	1	2025-08-05 04:41:22.693+05:30	1	2025-08-05 04:41:22.693+05:30
473	232	\N	PROB	9	Probation Review	Probation Review	परिवीक्षा समीक्षा	1	2025-08-05 04:41:22.693+05:30	1	2025-08-05 04:41:22.693+05:30
474	232	\N	CONFIRM	10	Confirmation Process	Confirmation Process	पुष्टि प्रक्रिया	1	2025-08-05 04:41:22.693+05:30	1	2025-08-05 04:41:22.693+05:30
475	232	\N	PROMOTE	11	Promotion Process	Promotion Process	पदोन्नति प्रक्रिया	1	2025-08-05 04:41:22.693+05:30	1	2025-08-05 04:41:22.693+05:30
476	232	\N	COMPLAIN	12	Complaint Handling	Complaint Handling	शिकायत प्रबंधन	1	2025-08-05 04:41:22.693+05:30	1	2025-08-05 04:41:22.693+05:30
477	232	\N	GRIEV	13	Grievance Redressal	Grievance Redressal	शिकायत निवारण	1	2025-08-05 04:41:22.693+05:30	1	2025-08-05 04:41:22.693+05:30
478	233	\N	NOTSTARTED	1	Not Started	Not Started	शुरू नहीं हुआ	1	2025-08-05 04:53:00.53+05:30	1	2025-08-05 04:53:00.53+05:30
479	233	\N	INPROGRESS	2	In Progress	In Progress	प्रगति पर	1	2025-08-05 04:53:00.53+05:30	1	2025-08-05 04:53:00.53+05:30
480	233	\N	COMPLETED	3	Completed	Completed	पूर्ण	1	2025-08-05 04:53:00.53+05:30	1	2025-08-05 04:53:00.53+05:30
481	233	\N	ONHOLD	4	On Hold	On Hold	स्थगित	1	2025-08-05 04:53:00.53+05:30	1	2025-08-05 04:53:00.53+05:30
482	233	\N	CANCELLED	5	Cancelled	Cancelled	रद्द कर दिया गया	1	2025-08-05 04:53:00.53+05:30	1	2025-08-05 04:53:00.53+05:30
483	233	\N	OVERDUE	6	Overdue	Overdue	समय सीमा पार	1	2025-08-05 04:53:00.53+05:30	1	2025-08-05 04:53:00.53+05:30
484	233	\N	APPROVED	7	Approved	Approved	अनुमोदित	1	2025-08-05 04:53:00.53+05:30	1	2025-08-05 04:53:00.53+05:30
485	233	\N	REJECTED	8	Rejected	Rejected	अस्वीकृत	1	2025-08-05 04:53:00.53+05:30	1	2025-08-05 04:53:00.53+05:30
486	234	\N	PENDING	1	Pending	Pending	लंबित	1	2025-08-05 06:29:52.21+05:30	1	2025-08-05 06:29:52.21+05:30
487	234	\N	INPROGRESS	2	In Progress	In Progress	प्रगति पर	1	2025-08-05 06:29:52.21+05:30	1	2025-08-05 06:29:52.21+05:30
488	234	\N	COMPLETED	3	Completed	Completed	पूर्ण	1	2025-08-05 06:29:52.21+05:30	1	2025-08-05 06:29:52.21+05:30
489	234	\N	APPROVED	4	Approved	Approved	स्वीकृत	1	2025-08-05 06:29:52.21+05:30	1	2025-08-05 06:29:52.21+05:30
490	234	\N	REJECTED	5	Rejected	Rejected	अस्वीकृत	1	2025-08-05 06:29:52.21+05:30	1	2025-08-05 06:29:52.21+05:30
491	234	\N	SKIPPED	6	Skipped	Skipped	छोड़ा गया	1	2025-08-05 06:29:52.21+05:30	1	2025-08-05 06:29:52.21+05:30
492	234	\N	ONHOLD	7	On Hold	On Hold	रोक दिया गया	1	2025-08-05 06:29:52.21+05:30	1	2025-08-05 06:29:52.21+05:30
566	331	\N	JAN	1	01	January	जनवरी	1	2025-08-17 06:01:43.87+05:30	\N	\N
567	331	\N	FEB	2	02	February	फ़रवरी	1	2025-08-17 06:01:43.87+05:30	\N	\N
568	331	\N	MAR	3	03	March	मार्च	1	2025-08-17 06:01:43.87+05:30	\N	\N
569	331	\N	APR	4	04	April	अप्रैल	1	2025-08-17 06:01:43.87+05:30	\N	\N
570	331	\N	MAY	5	05	May	मई	1	2025-08-17 06:01:43.87+05:30	\N	\N
571	331	\N	JUN	6	06	June	जून	1	2025-08-17 06:01:43.87+05:30	\N	\N
572	331	\N	JUL	7	07	July	जुलाई	1	2025-08-17 06:01:43.87+05:30	\N	\N
573	331	\N	AUG	8	08	August	अगस्त	1	2025-08-17 06:01:43.87+05:30	\N	\N
574	331	\N	SEP	9	09	September	सितंबर	1	2025-08-17 06:01:43.87+05:30	\N	\N
575	331	\N	OCT	10	10	October	अक्टूबर	1	2025-08-17 06:01:43.87+05:30	\N	\N
576	331	\N	NOV	11	11	November	नवंबर	1	2025-08-17 06:01:43.87+05:30	\N	\N
577	331	\N	DEC	12	12	December	दिसंबर	1	2025-08-17 06:01:43.87+05:30	\N	\N
578	332	\N	INR	1	INR	Indian Rupee	भारतीय रुपया	1	2025-08-19 16:18:31.503+05:30	\N	\N
579	332	\N	USD	2	USD	US Dollar	अमेरिकी डॉलर	1	2025-08-19 16:18:31.503+05:30	\N	\N
580	332	\N	EUR	3	EUR	Euro	यूरो	1	2025-08-19 16:18:31.503+05:30	\N	\N
581	332	\N	GBP	4	GBP	British Pound	ब्रिटिश पाउंड	1	2025-08-19 16:18:31.503+05:30	\N	\N
582	332	\N	AED	5	AED	UAE Dirham	यूएई दिरहम	1	2025-08-19 16:18:31.503+05:30	\N	\N
583	333	\N	PAYTM	1	Paytm	Paytm	पे टी एम	1	2025-08-19 16:18:31.667+05:30	\N	\N
584	333	\N	RAZORPAY	2	Razorpay	Razorpay	रेज़रपे	1	2025-08-19 16:18:31.667+05:30	\N	\N
585	333	\N	CCAVENUE	3	CCAvenue	CCAvenue	सीसीएवन्यू	1	2025-08-19 16:18:31.667+05:30	\N	\N
586	333	\N	STRIPE	4	Stripe	Stripe	स्ट्राइप	1	2025-08-19 16:18:31.667+05:30	\N	\N
587	333	\N	PAYPAL	5	PayPal	PayPal	पेपाल	1	2025-08-19 16:18:31.667+05:30	\N	\N
588	334	\N	CASH	1	Cash	Cash	नकद	1	2026-02-23 16:04:54.758098+05:30	\N	\N
589	334	\N	BANK_TRANSFER	2	Bank Transfer	Bank Transfer	बैंक ट्रांसफर	1	2026-02-23 16:04:54.758098+05:30	\N	\N
590	334	\N	CHEQUE	3	Cheque	Cheque	चेक	1	2026-02-23 16:04:54.758098+05:30	\N	\N
591	334	\N	ONLINE	4	Online	Online	ऑनलाइन	1	2026-02-23 16:04:54.758098+05:30	\N	\N
592	335	\N	PENDING	1	Pending	Pending	लंबित	1	2026-02-24 12:21:07.309003+05:30	\N	\N
593	335	\N	COMPLETED	2	Completed	Completed	पूर्ण	1	2026-02-24 12:21:07.309003+05:30	\N	\N
594	335	\N	FAILED	3	Failed	Failed	असफल	1	2026-02-24 12:21:07.309003+05:30	\N	\N
595	335	\N	BOUNCED	4	Bounced/Refunded	Bounced/Refunded	वापसी/बाउंस	1	2026-02-24 12:21:07.309003+05:30	\N	\N
596	336	\N	UNPAID	1	Unpaid	Unpaid	अवैतनिक	1	2026-02-24 12:21:07.309003+05:30	\N	\N
597	336	\N	PARTIAL	2	Partially Paid	Partially Paid	आंशिक भुगतान	1	2026-02-24 12:21:07.309003+05:30	\N	\N
598	336	\N	PAID	3	Paid	Paid	भुगतान किया गया	1	2026-02-24 12:21:07.309003+05:30	\N	\N
599	336	\N	OVERDUE	4	Overdue	Overdue	देय तिथि पार	1	2026-02-24 12:21:07.309003+05:30	\N	\N
600	336	\N	CANCELLED	5	Cancelled	Cancelled	रद्द	1	2026-02-24 12:21:07.309003+05:30	\N	\N
601	337	\N	MERIT	1	Merit	Merit	मेधा आधारित	1	2026-02-24 12:21:07.309003+05:30	\N	\N
602	337	\N	SIBLING	2	Sibling	Sibling	सहोदर छूट	1	2026-02-24 12:21:07.309003+05:30	\N	\N
603	337	\N	STAFF	3	Staff Child	Staff Child	कर्मचारी संतान	1	2026-02-24 12:21:07.309003+05:30	\N	\N
604	337	\N	EARLY	4	Early Bird	Early Bird	शीघ्र भुगतान छूट	1	2026-02-24 12:21:07.309003+05:30	\N	\N
605	338	\N	PENDING	1	Pending	Pending	लंबित	1	2026-02-24 12:21:07.309003+05:30	\N	\N
606	338	\N	PARTIAL	2	Partially Paid	Partially Paid	आंशिक भुगतान	1	2026-02-24 12:21:07.309003+05:30	\N	\N
607	338	\N	PAID	3	Paid	Paid	भुगतान किया गया	1	2026-02-24 12:21:07.309003+05:30	\N	\N
608	338	\N	OVERDUE	4	Overdue	Overdue	देय तिथि पार	1	2026-02-24 12:21:07.309003+05:30	\N	\N
609	339	\N	CASH	1	Cash	Cash	नकद	1	2026-02-24 12:21:07.309003+05:30	\N	\N
610	339	\N	CHEQUE	2	Cheque	Cheque	चेक	1	2026-02-24 12:21:07.309003+05:30	\N	\N
611	339	\N	ONLINE	3	Online	Online	ऑनलाइन	1	2026-02-24 12:21:07.309003+05:30	\N	\N
612	339	\N	BANK_TRANSFER	4	Bank Transfer	Bank Transfer	बैंक ट्रांसफर	1	2026-02-24 12:21:07.309003+05:30	\N	\N
613	340	\N	PENDING	1	Pending	Pending	लंबित	1	2026-02-24 12:21:07.309003+05:30	\N	\N
614	340	\N	APPROVED	2	Approved	Approved	स्वीकृत	1	2026-02-24 12:21:07.309003+05:30	\N	\N
615	340	\N	REJECTED	3	Rejected	Rejected	अस्वीकृत	1	2026-02-24 12:21:07.309003+05:30	\N	\N
1051	341	\N	SINGLE	1	Single	Single	अविवाहित	1	2026-02-28 13:12:23.162518+05:30	\N	\N
1052	341	\N	MARRIED	2	Married	Married	विवाहित	1	2026-02-28 13:12:23.162518+05:30	\N	\N
1053	341	\N	DIVORCED	3	Divorced	Divorced	तलाकशुदा	1	2026-02-28 13:12:23.162518+05:30	\N	\N
1054	341	\N	WIDOWED	4	Widowed	Widowed	विधवा/विधुर	1	2026-02-28 13:12:23.162518+05:30	\N	\N
1001	342	\N	ENGLISH	1	English	English	अंग्रेज़ी	1	2026-02-28 13:15:14.409034+05:30	\N	\N
1002	342	\N	HINDI	2	Hindi	Hindi	हिन्दी	1	2026-02-28 13:15:14.409034+05:30	\N	\N
1003	342	\N	MARATHI	3	Marathi	Marathi	मराठी	1	2026-02-28 13:15:14.409034+05:30	\N	\N
1004	342	\N	TELUGU	4	Telugu	Telugu	तेलुगु	1	2026-02-28 13:15:14.409034+05:30	\N	\N
1005	342	\N	TAMIL	5	Tamil	Tamil	तमिल	1	2026-02-28 13:15:14.409034+05:30	\N	\N
1006	342	\N	GUJARATI	6	Gujarati	Gujarati	गुजराती	1	2026-02-28 13:15:14.409034+05:30	\N	\N
1007	342	\N	URDU	7	Urdu	Urdu	उर्दू	1	2026-02-28 13:15:14.409034+05:30	\N	\N
1008	342	\N	BENGALI	8	Bengali	Bengali	बंगाली	1	2026-02-28 13:15:14.409034+05:30	\N	\N
1009	342	\N	KANNADA	9	Kannada	Kannada	कन्नड़	1	2026-02-28 13:15:14.409034+05:30	\N	\N
1010	342	\N	MALAYALAM	10	Malayalam	Malayalam	मलयालम	1	2026-02-28 13:15:14.409034+05:30	\N	\N
616	343	\N	CLASSROOM	1	Classroom	Classroom	Classroom	1	2026-02-28 14:52:27.607002+05:30	\N	\N
617	343	\N	LAB	2	Lab	Lab	Lab	1	2026-02-28 14:52:27.607002+05:30	\N	\N
618	343	\N	CONFERENCE	3	Conference Room	Conference Room	Conference Room	1	2026-02-28 14:52:27.607002+05:30	\N	\N
619	343	\N	OFFICE	4	Office	Office	Office	1	2026-02-28 14:52:27.607002+05:30	\N	\N
15	52	\N	CLOCK_IN	1	Clock In	Clock In	प्रवेश	1	2026-03-05 13:52:28.895025+05:30	\N	\N
16	52	\N	CLOCK_OUT	2	Clock Out	Clock Out	निकास	1	2026-03-05 13:52:28.895025+05:30	\N	\N
17	51	\N	PRESENT	1	Present	Present	उपस्थित	1	2026-03-05 13:52:33.789802+05:30	\N	\N
18	51	\N	ABSENT	2	Absent	Absent	अनुपस्थित	1	2026-03-05 13:52:33.789802+05:30	\N	\N
19	51	\N	HALF_DAY	3	Half Day	Half Day	आधा दिन	1	2026-03-05 13:52:33.789802+05:30	\N	\N
20	51	\N	ON_LEAVE	4	On Leave	On Leave	अवकाश	1	2026-03-05 13:52:33.789802+05:30	\N	\N
21	51	\N	LATE	5	Late	Late	देर से	1	2026-03-05 13:52:33.789802+05:30	\N	\N
22	51	\N	WFH	6	Work From Home	Work From Home	घर से कार्य	1	2026-03-05 13:52:33.789802+05:30	\N	\N
23	51	\N	HOLIDAY	7	Holiday	Holiday	अवकाश दिवस	1	2026-03-05 13:52:33.789802+05:30	\N	\N
24	51	\N	WEEKEND	8	Weekend	Weekend	सप्ताहांत	1	2026-03-05 13:52:33.789802+05:30	\N	\N
25	50	\N	PENDING	1	Pending	Pending	लंबित	1	2026-03-05 13:52:38.650813+05:30	\N	\N
26	50	\N	APPROVED	2	Approved	Approved	स्वीकृत	1	2026-03-05 13:52:38.650813+05:30	\N	\N
27	50	\N	REJECTED	3	Rejected	Rejected	अस्वीकृत	1	2026-03-05 13:52:38.650813+05:30	\N	\N
28	50	\N	CANCELLED	4	Cancelled	Cancelled	रद्द	1	2026-03-05 13:52:38.650813+05:30	\N	\N
29	351	\N	OFFICE	1	Office	Office	\N	1	2026-03-05 17:31:55.975418+05:30	\N	\N
30	351	\N	WFH	2	Work From Home	Work From Home	\N	1	2026-03-05 17:31:55.975418+05:30	\N	\N
31	351	\N	FIELD	3	Field Work	Field Work	\N	1	2026-03-05 17:31:55.975418+05:30	\N	\N
32	351	\N	HYBRID	4	Hybrid	Hybrid	\N	1	2026-03-05 17:31:55.975418+05:30	\N	\N
33	352	\N	NONE	1	No Correction	No Correction	\N	1	2026-03-05 17:32:00.822785+05:30	\N	\N
34	352	\N	REQUESTED	2	Correction Requested	Correction Requested	\N	1	2026-03-05 17:32:00.822785+05:30	\N	\N
35	352	\N	APPROVED	3	Correction Approved	Correction Approved	\N	1	2026-03-05 17:32:00.822785+05:30	\N	\N
36	352	\N	REJECTED	4	Correction Rejected	Correction Rejected	\N	1	2026-03-05 17:32:00.822785+05:30	\N	\N
1055	7	\N	NURSERY	1	Nursery	Nursery	नर्सरी	\N	2026-03-06 10:00:00+05:30	\N	\N
1056	7	\N	LKG	2	LKG	LKG	एल.के.जी	\N	2026-03-06 10:00:00+05:30	\N	\N
1057	7	\N	UKG	3	UKG	UKG	यू.के.जी	\N	2026-03-06 10:00:00+05:30	\N	\N
1058	7	\N	Class1	4	1st	1st	कक्षा 1	\N	2025-03-18 09:40:26.263+05:30	\N	\N
1059	7	\N	Class2	5	2nd	2nd	कक्षा 2	\N	2025-03-18 09:40:26.3+05:30	\N	\N
1060	7	\N	Class3	6	3rd	3rd	कक्षा 3	\N	2025-03-18 09:40:26.33+05:30	\N	\N
1061	7	\N	Class4	7	4th	4th	कक्षा 4	\N	2025-03-18 09:40:26.367+05:30	\N	\N
1062	7	\N	Class5	8	5th	5th	कक्षा 5	\N	2025-03-18 09:40:26.403+05:30	\N	\N
1063	7	\N	Class6	9	6th	6th	कक्षा 6	\N	2025-03-18 09:40:26.437+05:30	\N	\N
1064	7	\N	Class7	10	7th	7th	कक्षा 7	\N	2025-03-18 09:40:26.47+05:30	\N	\N
1065	7	\N	Class8	11	8th	8th	कक्षा 8	\N	2025-03-18 09:40:26.507+05:30	\N	\N
1066	7	\N	Class9	12	9th	9th	कक्षा 9	\N	2025-03-18 09:40:26.54+05:30	\N	\N
1067	7	\N	Class10	13	10th	10th	कक्षा 10	\N	2025-03-18 09:40:26.577+05:30	\N	\N
1068	7	\N	Class11_Med	14	11th (Medical)	11th (Medical)	कक्षा 11 (मेडिकल)	\N	2026-03-06 10:00:00+05:30	\N	\N
1069	7	\N	Class11_NonMed	15	11th (Non Medical)	11th (Non Medical)	कक्षा 11 (नॉन मेडिकल)	\N	2026-03-06 10:00:00+05:30	\N	\N
1070	7	\N	Class11_Arts	16	11th (Arts)	11th (Arts)	कक्षा 11 (आर्ट्स)	\N	2026-03-06 10:00:00+05:30	\N	\N
1071	7	\N	Class12_Med	17	12th (Medical)	12th (Medical)	कक्षा 12 (मेडिकल)	\N	2026-03-06 10:00:00+05:30	\N	\N
1072	7	\N	Class12_NonMed	18	12th (Non Medical)	12th (Non Medical)	कक्षा 12 (नॉन मेडिकल)	\N	2026-03-06 10:00:00+05:30	\N	\N
1073	7	\N	Class12_Arts	19	12th (Arts)	12th (Arts)	कक्षा 12 (आर्ट्स)	\N	2026-03-06 10:00:00+05:30	\N	\N
1074	8	\N	Drawing	\N	\N	DRAWING	\N	\N	2026-04-27 12:41:51.631466+05:30	\N	\N
1075	8	\N	EVS	\N	\N	E.V.S	\N	\N	2026-04-27 12:41:51.631466+05:30	\N	\N
1076	8	\N	Computer	\N	\N	COMPUTER	\N	\N	2026-04-27 12:41:51.631466+05:30	\N	\N
1077	8	\N	GK	\N	\N	G.K	\N	\N	2026-04-27 12:41:51.631466+05:30	\N	\N
4337	355	4336	google_url	\N	https://generativelanguage.googleapis.com/v1beta/openai/chat/completions	Google URL	\N	0	2026-06-19 03:53:59.496572+05:30	\N	\N
4338	354	4336	gemini-3.1-flash-image	0	\N	Nano Banana 2 (Gemini 3.1 Flash Image)	\N	0	2026-06-19 03:53:59.501234+05:30	\N	\N
4339	354	4336	gemini-3-pro-image	1	\N	Nano Banana Pro (Gemini 3 Pro Image)	\N	0	2026-06-19 03:53:59.510352+05:30	\N	\N
4340	353	\N	cohere	\N	\N	Cohere	\N	0	2026-06-19 03:53:59.51262+05:30	\N	\N
4341	355	4340	cohere_url	\N	https://api.cohere.ai/v1/chat/completions	Cohere URL	\N	0	2026-06-19 03:53:59.514692+05:30	\N	\N
4342	354	4340	north-mini-code:free	2	\N	North Mini Code (free)	\N	0	2026-06-19 03:53:59.516714+05:30	\N	\N
4343	353	\N	anthropic	\N	\N	Anthropic	\N	0	2026-06-19 03:53:59.519653+05:30	\N	\N
4344	355	4343	anthropic_url	\N	https://api.anthropic.com/v1/messages	Anthropic URL	\N	0	2026-06-19 03:53:59.523085+05:30	\N	\N
4345	354	4343	claude-fable-5	7	\N	Claude Fable 5	\N	0	2026-06-19 03:53:59.526447+05:30	\N	\N
4346	353	\N	nvidia	\N	\N	NVIDIA	\N	0	2026-06-19 03:53:59.528163+05:30	\N	\N
4347	355	4346	nvidia_url	\N	https://api.nvidia.com/v1/chat/completions	NVIDIA URL	\N	0	2026-06-19 03:53:59.530555+05:30	\N	\N
4348	354	4346	nemotron-3.5-content-safety:free	9	\N	Nemotron 3.5 Content Safety (free)	\N	0	2026-06-19 03:53:59.532128+05:30	\N	\N
4349	354	4346	nemotron-3-ultra-550b-a55b:free	10	\N	Nemotron 3 Ultra (free)	\N	0	2026-06-19 03:53:59.534072+05:30	\N	\N
4350	354	4346	nemotron-3-ultra-550b-a55b	11	\N	Nemotron 3 Ultra	\N	0	2026-06-19 03:53:59.536061+05:30	\N	\N
4351	353	\N	qwen	\N	\N	Qwen	\N	0	2026-06-19 03:53:59.537798+05:30	\N	\N
4352	355	4351	qwen_url	\N	https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions	Qwen URL	\N	0	2026-06-19 03:53:59.539575+05:30	\N	\N
4353	354	4351	qwen3.7-plus	12	\N	Qwen3.7 Plus	\N	0	2026-06-19 03:53:59.542536+05:30	\N	\N
4354	353	\N	minimax	\N	\N	MiniMax	\N	0	2026-06-19 03:53:59.546726+05:30	\N	\N
4355	355	4354	minimax_url	\N	https://api.minimax.com/v1/chat/completions	MiniMax URL	\N	0	2026-06-19 03:53:59.550231+05:30	\N	\N
4356	354	4354	minimax-m3	13	\N	MiniMax M3	\N	0	2026-06-19 03:53:59.554229+05:30	\N	\N
4357	354	4343	claude-opus-4.8-fast	15	\N	Claude Opus 4.8 (Fast)	\N	0	2026-06-19 03:53:59.557132+05:30	\N	\N
4358	354	4343	claude-opus-4.8	16	\N	Claude Opus 4.8	\N	0	2026-06-19 03:53:59.559455+05:30	\N	\N
4359	354	4351	qwen3.7-max	17	\N	Qwen3.7 Max	\N	0	2026-06-19 03:53:59.560812+05:30	\N	\N
4360	354	4336	gemini-3.5-flash	19	\N	Gemini 3.5 Flash	\N	0	2026-06-19 03:53:59.56382+05:30	\N	\N
4361	354	4343	claude-opus-4.7-fast	20	\N	Claude Opus 4.7 (Fast)	\N	0	2026-06-19 03:53:59.565183+05:30	\N	\N
4362	354	4336	gemini-3.1-flash-lite	23	\N	Gemini 3.1 Flash Lite	\N	0	2026-06-19 03:53:59.567157+05:30	\N	\N
4363	353	\N	openai	\N	\N	OpenAI	\N	0	2026-06-19 03:53:59.568287+05:30	\N	\N
4364	355	4363	openai_url	\N	https://api.openai.com/v1/chat/completions	OpenAI URL	\N	0	2026-06-19 03:53:59.569139+05:30	\N	\N
4365	354	4363	gpt-chat-latest	24	\N	GPT Chat Latest	\N	0	2026-06-19 03:53:59.569961+05:30	\N	\N
4366	353	\N	mistralai	\N	\N	Mistral	\N	0	2026-06-19 03:53:59.572547+05:30	\N	\N
4367	355	4366	mistralai_url	\N	https://api.mistral.ai/v1/chat/completions	Mistral URL	\N	0	2026-06-19 03:53:59.574731+05:30	\N	\N
4368	354	4366	mistral-medium-3-5	27	\N	Mistral Medium 3.5	\N	0	2026-06-19 03:53:59.575867+05:30	\N	\N
4369	354	4346	nemotron-3-nano-omni-30b-a3b-reasoning:free	29	\N	Nemotron 3 Nano Omni (free)	\N	0	2026-06-19 03:53:59.576681+05:30	\N	\N
4370	354	4351	qwen3.5-plus-20260420	41	\N	Qwen3.5 Plus 2026-04-20	\N	0	2026-06-19 03:53:59.577717+05:30	\N	\N
4371	354	4351	qwen3.6-flash	42	\N	Qwen3.6 Flash	\N	0	2026-06-19 03:53:59.578855+05:30	\N	\N
4372	354	4351	qwen3.6-35b-a3b	43	\N	Qwen3.6 35B A3B	\N	0	2026-06-19 03:53:59.580022+05:30	\N	\N
4373	354	4351	qwen3.6-max-preview	44	\N	Qwen3.6 Max Preview	\N	0	2026-06-19 03:53:59.580876+05:30	\N	\N
4374	354	4351	qwen3.6-27b	45	\N	Qwen3.6 27B	\N	0	2026-06-19 03:53:59.581665+05:30	\N	\N
4375	354	4363	gpt-5.5-pro	46	\N	GPT-5.5 Pro	\N	0	2026-06-19 03:53:59.583634+05:30	\N	\N
4376	354	4363	gpt-5.5	47	\N	GPT-5.5	\N	0	2026-06-19 03:53:59.584596+05:30	\N	\N
4377	353	\N	deepseek	\N	\N	DeepSeek	\N	0	2026-06-19 03:53:59.585374+05:30	\N	\N
4378	355	4377	deepseek_url	\N	https://api.deepseek.com/v1/chat/completions	DeepSeek URL	\N	0	2026-06-19 03:53:59.587304+05:30	\N	\N
4379	354	4377	deepseek-v4-pro	48	\N	DeepSeek V4 Pro	\N	0	2026-06-19 03:53:59.588244+05:30	\N	\N
4380	354	4377	deepseek-v4-flash	49	\N	DeepSeek V4 Flash	\N	0	2026-06-19 03:53:59.589186+05:30	\N	\N
4381	354	4363	gpt-5.4-image-2	54	\N	GPT-5.4 Image 2	\N	0	2026-06-19 03:53:59.590201+05:30	\N	\N
4382	354	4343	claude-opus-4.7	59	\N	Claude Opus 4.7	\N	0	2026-06-19 03:53:59.592498+05:30	\N	\N
4383	354	4343	claude-opus-4.6-fast	60	\N	Claude Opus 4.6 (Fast)	\N	0	2026-06-19 03:53:59.593705+05:30	\N	\N
4384	354	4336	gemma-4-26b-a4b-it:free	62	\N	Gemma 4 26B A4B  (free)	\N	0	2026-06-19 03:53:59.59476+05:30	\N	\N
4385	354	4336	gemma-4-26b-a4b-it	63	\N	Gemma 4 26B A4B	\N	0	2026-06-19 03:53:59.595688+05:30	\N	\N
4386	354	4336	gemma-4-31b-it:free	64	\N	Gemma 4 31B (free)	\N	0	2026-06-19 03:53:59.596882+05:30	\N	\N
4387	354	4336	gemma-4-31b-it	65	\N	Gemma 4 31B	\N	0	2026-06-19 03:53:59.597867+05:30	\N	\N
4388	354	4351	qwen3.6-plus	66	\N	Qwen3.6 Plus	\N	0	2026-06-19 03:53:59.599114+05:30	\N	\N
4389	354	4336	lyria-3-pro-preview	70	\N	Lyria 3 Pro Preview	\N	0	2026-06-19 03:53:59.601198+05:30	\N	\N
4390	354	4336	lyria-3-clip-preview	71	\N	Lyria 3 Clip Preview	\N	0	2026-06-19 03:53:59.603646+05:30	\N	\N
4391	354	4354	minimax-m2.7	74	\N	MiniMax M2.7	\N	0	2026-06-19 03:53:59.605384+05:30	\N	\N
4392	354	4363	gpt-5.4-nano	75	\N	GPT-5.4 Nano	\N	0	2026-06-19 03:53:59.606595+05:30	\N	\N
4393	354	4363	gpt-5.4-mini	76	\N	GPT-5.4 Mini	\N	0	2026-06-19 03:53:59.607438+05:30	\N	\N
4394	354	4366	mistral-small-2603	77	\N	Mistral Small 4	\N	0	2026-06-19 03:53:59.610792+05:30	\N	\N
4395	354	4346	nemotron-3-super-120b-a12b:free	79	\N	Nemotron 3 Super (free)	\N	0	2026-06-19 03:53:59.611745+05:30	\N	\N
4396	354	4346	nemotron-3-super-120b-a12b	80	\N	Nemotron 3 Super	\N	0	2026-06-19 03:53:59.612564+05:30	\N	\N
4397	354	4351	qwen3.5-9b	82	\N	Qwen3.5-9B	\N	0	2026-06-19 03:53:59.613437+05:30	\N	\N
4398	354	4363	gpt-5.4-pro	83	\N	GPT-5.4 Pro	\N	0	2026-06-19 03:53:59.614254+05:30	\N	\N
4399	354	4363	gpt-5.4	84	\N	GPT-5.4	\N	0	2026-06-19 03:53:59.615947+05:30	\N	\N
4400	354	4363	gpt-5.3-chat	86	\N	GPT-5.3 Chat	\N	0	2026-06-19 03:53:59.616797+05:30	\N	\N
4401	354	4336	gemini-3.1-flash-lite-preview	87	\N	Gemini 3.1 Flash Lite Preview	\N	0	2026-06-19 03:53:59.617748+05:30	\N	\N
4402	354	4336	gemini-3.1-flash-image-preview	89	\N	Nano Banana 2 (Gemini 3.1 Flash Image Preview)	\N	0	2026-06-19 03:53:59.620445+05:30	\N	\N
4403	354	4351	qwen3.5-35b-a3b	90	\N	Qwen3.5-35B-A3B	\N	0	2026-06-19 03:53:59.623961+05:30	\N	\N
4404	354	4351	qwen3.5-27b	91	\N	Qwen3.5-27B	\N	0	2026-06-19 03:53:59.626129+05:30	\N	\N
4405	354	4351	qwen3.5-122b-a10b	92	\N	Qwen3.5-122B-A10B	\N	0	2026-06-19 03:53:59.62722+05:30	\N	\N
4406	354	4351	qwen3.5-flash-02-23	93	\N	Qwen3.5-Flash	\N	0	2026-06-19 03:53:59.628147+05:30	\N	\N
4407	354	4336	gemini-3.1-pro-preview-customtools	95	\N	Gemini 3.1 Pro Preview Custom Tools	\N	0	2026-06-19 03:53:59.628917+05:30	\N	\N
4408	354	4363	gpt-5.3-codex	96	\N	GPT-5.3-Codex	\N	0	2026-06-19 03:53:59.63049+05:30	\N	\N
4409	354	4336	gemini-3.1-pro-preview	98	\N	Gemini 3.1 Pro Preview	\N	0	2026-06-19 03:53:59.631455+05:30	\N	\N
4410	354	4343	claude-sonnet-4.6	99	\N	Claude Sonnet 4.6	\N	0	2026-06-19 03:53:59.632133+05:30	\N	\N
4411	354	4351	qwen3.5-plus-02-15	100	\N	Qwen3.5 Plus 2026-02-15	\N	0	2026-06-19 03:53:59.632937+05:30	\N	\N
4412	354	4351	qwen3.5-397b-a17b	101	\N	Qwen3.5 397B A17B	\N	0	2026-06-19 03:53:59.63372+05:30	\N	\N
4413	354	4354	minimax-m2.5	102	\N	MiniMax M2.5	\N	0	2026-06-19 03:53:59.634625+05:30	\N	\N
4414	354	4351	qwen3-max-thinking	104	\N	Qwen3 Max Thinking	\N	0	2026-06-19 03:53:59.636322+05:30	\N	\N
4415	354	4343	claude-opus-4.6	105	\N	Claude Opus 4.6	\N	0	2026-06-19 03:53:59.643828+05:30	\N	\N
4416	354	4351	qwen3-coder-next	106	\N	Qwen3 Coder Next	\N	0	2026-06-19 03:53:59.645133+05:30	\N	\N
4417	354	4354	minimax-m2-her	111	\N	MiniMax M2-her	\N	0	2026-06-19 03:53:59.648159+05:30	\N	\N
4418	354	4363	gpt-audio	115	\N	GPT Audio	\N	0	2026-06-19 03:53:59.650482+05:30	\N	\N
4419	354	4363	gpt-audio-mini	116	\N	GPT Audio Mini	\N	0	2026-06-19 03:53:59.65204+05:30	\N	\N
4420	354	4363	gpt-5.2-codex	118	\N	GPT-5.2-Codex	\N	0	2026-06-19 03:53:59.653445+05:30	\N	\N
4421	354	4354	minimax-m2.1	121	\N	MiniMax M2.1	\N	0	2026-06-19 03:53:59.654551+05:30	\N	\N
4422	354	4336	gemini-3-flash-preview	123	\N	Gemini 3 Flash Preview	\N	0	2026-06-19 03:53:59.655734+05:30	\N	\N
4423	354	4346	nemotron-3-nano-30b-a3b:free	124	\N	Nemotron 3 Nano 30B A3B (free)	\N	0	2026-06-19 03:53:59.656696+05:30	\N	\N
4424	354	4346	nemotron-3-nano-30b-a3b	125	\N	Nemotron 3 Nano 30B A3B	\N	0	2026-06-19 03:53:59.658122+05:30	\N	\N
4425	354	4363	gpt-5.2-chat	126	\N	GPT-5.2 Chat	\N	0	2026-06-19 03:53:59.663937+05:30	\N	\N
4426	354	4363	gpt-5.2-pro	127	\N	GPT-5.2 Pro	\N	0	2026-06-19 03:53:59.665554+05:30	\N	\N
4427	354	4363	gpt-5.2	128	\N	GPT-5.2	\N	0	2026-06-19 03:53:59.668695+05:30	\N	\N
4428	354	4366	devstral-2512	129	\N	Devstral 2 2512	\N	0	2026-06-19 03:53:59.670348+05:30	\N	\N
4429	354	4363	gpt-5.1-codex-max	134	\N	GPT-5.1-Codex-Max	\N	0	2026-06-19 03:53:59.673133+05:30	\N	\N
4430	353	\N	amazon	\N	\N	Amazon	\N	0	2026-06-19 03:53:59.674562+05:30	\N	\N
4431	355	4430	amazon_url	\N	https://api.amazon.com/v1/chat/completions	Amazon URL	\N	0	2026-06-19 03:53:59.675533+05:30	\N	\N
4432	354	4430	nova-2-lite-v1	135	\N	Nova 2 Lite	\N	0	2026-06-19 03:53:59.676689+05:30	\N	\N
4433	354	4366	ministral-14b-2512	136	\N	Ministral 3 14B 2512	\N	0	2026-06-19 03:53:59.67779+05:30	\N	\N
4434	354	4366	ministral-8b-2512	137	\N	Ministral 3 8B 2512	\N	0	2026-06-19 03:53:59.678803+05:30	\N	\N
4435	354	4366	ministral-3b-2512	138	\N	Ministral 3 3B 2512	\N	0	2026-06-19 03:53:59.67953+05:30	\N	\N
4436	354	4366	mistral-large-2512	139	\N	Mistral Large 3 2512	\N	0	2026-06-19 03:53:59.68512+05:30	\N	\N
4437	354	4377	deepseek-v3.2	141	\N	DeepSeek V3.2	\N	0	2026-06-19 03:53:59.686833+05:30	\N	\N
4438	354	4343	claude-opus-4.5	143	\N	Claude Opus 4.5	\N	0	2026-06-19 03:53:59.687753+05:30	\N	\N
4439	354	4336	gemini-3-pro-image-preview	145	\N	Nano Banana Pro (Gemini 3 Pro Image Preview)	\N	0	2026-06-19 03:53:59.688749+05:30	\N	\N
4440	354	4363	gpt-5.1	147	\N	GPT-5.1	\N	0	2026-06-19 03:53:59.690219+05:30	\N	\N
4441	354	4363	gpt-5.1-chat	148	\N	GPT-5.1 Chat	\N	0	2026-06-19 03:53:59.691009+05:30	\N	\N
4442	354	4363	gpt-5.1-codex	149	\N	GPT-5.1-Codex	\N	0	2026-06-19 03:53:59.692383+05:30	\N	\N
4443	354	4363	gpt-5.1-codex-mini	150	\N	GPT-5.1-Codex-Mini	\N	0	2026-06-19 03:53:59.693479+05:30	\N	\N
4444	354	4430	nova-premier-v1	152	\N	Nova Premier 1.0	\N	0	2026-06-19 03:53:59.694172+05:30	\N	\N
4445	354	4366	voxtral-small-24b-2507	154	\N	Voxtral Small 24B 2507	\N	0	2026-06-19 03:53:59.69482+05:30	\N	\N
4446	354	4363	gpt-oss-safeguard-20b	155	\N	gpt-oss-safeguard-20b	\N	0	2026-06-19 03:53:59.695547+05:30	\N	\N
4447	354	4346	nemotron-nano-12b-v2-vl:free	156	\N	Nemotron Nano 12B 2 VL (free)	\N	0	2026-06-19 03:53:59.696386+05:30	\N	\N
4448	354	4354	minimax-m2	157	\N	MiniMax M2	\N	0	2026-06-19 03:53:59.697456+05:30	\N	\N
4449	354	4351	qwen3-vl-32b-instruct	158	\N	Qwen3 VL 32B Instruct	\N	0	2026-06-19 03:53:59.701471+05:30	\N	\N
4450	354	4363	gpt-5-image-mini	161	\N	GPT-5 Image Mini	\N	0	2026-06-19 03:53:59.702728+05:30	\N	\N
4451	354	4343	claude-haiku-4.5	162	\N	Claude Haiku 4.5	\N	0	2026-06-19 03:53:59.704469+05:30	\N	\N
4452	354	4351	qwen3-vl-8b-thinking	163	\N	Qwen3 VL 8B Thinking	\N	0	2026-06-19 03:53:59.709587+05:30	\N	\N
4453	354	4351	qwen3-vl-8b-instruct	164	\N	Qwen3 VL 8B Instruct	\N	0	2026-06-19 03:53:59.711128+05:30	\N	\N
4454	354	4363	gpt-5-image	165	\N	GPT-5 Image	\N	0	2026-06-19 03:53:59.713243+05:30	\N	\N
4455	354	4363	o3-deep-research	166	\N	o3 Deep Research	\N	0	2026-06-19 03:53:59.716259+05:30	\N	\N
4456	354	4363	o4-mini-deep-research	167	\N	o4 Mini Deep Research	\N	0	2026-06-19 03:53:59.718776+05:30	\N	\N
4457	354	4346	llama-3.3-nemotron-super-49b-v1.5	168	\N	Llama 3.3 Nemotron Super 49B V1.5	\N	0	2026-06-19 03:53:59.719772+05:30	\N	\N
4458	354	4336	gemini-2.5-flash-image	169	\N	Nano Banana (Gemini 2.5 Flash Image)	\N	0	2026-06-19 03:53:59.720893+05:30	\N	\N
4459	354	4351	qwen3-vl-30b-a3b-thinking	170	\N	Qwen3 VL 30B A3B Thinking	\N	0	2026-06-19 03:53:59.722061+05:30	\N	\N
4460	354	4351	qwen3-vl-30b-a3b-instruct	171	\N	Qwen3 VL 30B A3B Instruct	\N	0	2026-06-19 03:53:59.724301+05:30	\N	\N
4461	354	4363	gpt-5-pro	172	\N	GPT-5 Pro	\N	0	2026-06-19 03:53:59.725827+05:30	\N	\N
4462	354	4343	claude-sonnet-4.5	174	\N	Claude Sonnet 4.5	\N	0	2026-06-19 03:53:59.726756+05:30	\N	\N
4463	354	4377	deepseek-v3.2-exp	175	\N	DeepSeek V3.2 Exp	\N	0	2026-06-19 03:53:59.728855+05:30	\N	\N
4464	354	4336	gemini-2.5-flash-lite-preview-09-2025	178	\N	Gemini 2.5 Flash Lite Preview 09-2025	\N	0	2026-06-19 03:53:59.729955+05:30	\N	\N
4465	354	4351	qwen3-vl-235b-a22b-thinking	179	\N	Qwen3 VL 235B A22B Thinking	\N	0	2026-06-19 03:53:59.73084+05:30	\N	\N
4466	354	4351	qwen3-vl-235b-a22b-instruct	180	\N	Qwen3 VL 235B A22B Instruct	\N	0	2026-06-19 03:53:59.73257+05:30	\N	\N
4467	354	4351	qwen3-max	181	\N	Qwen3 Max	\N	0	2026-06-19 03:53:59.734227+05:30	\N	\N
4468	354	4351	qwen3-coder-plus	182	\N	Qwen3 Coder Plus	\N	0	2026-06-19 03:53:59.735564+05:30	\N	\N
4469	354	4363	gpt-5-codex	183	\N	GPT-5 Codex	\N	0	2026-06-19 03:53:59.737751+05:30	\N	\N
4470	354	4377	deepseek-v3.1-terminus	184	\N	DeepSeek V3.1 Terminus	\N	0	2026-06-19 03:53:59.739183+05:30	\N	\N
4471	354	4351	qwen3-coder-flash	185	\N	Qwen3 Coder Flash	\N	0	2026-06-19 03:53:59.742457+05:30	\N	\N
4472	354	4351	qwen3-next-80b-a3b-thinking	186	\N	Qwen3 Next 80B A3B Thinking	\N	0	2026-06-19 03:53:59.744591+05:30	\N	\N
4473	354	4351	qwen3-next-80b-a3b-instruct:free	187	\N	Qwen3 Next 80B A3B Instruct (free)	\N	0	2026-06-19 03:53:59.748827+05:30	\N	\N
4474	354	4351	qwen3-next-80b-a3b-instruct	188	\N	Qwen3 Next 80B A3B Instruct	\N	0	2026-06-19 03:53:59.750006+05:30	\N	\N
4475	354	4351	qwen-plus-2025-07-28:thinking	189	\N	Qwen Plus 0728 (thinking)	\N	0	2026-06-19 03:53:59.750971+05:30	\N	\N
4476	354	4351	qwen-plus-2025-07-28	190	\N	Qwen Plus 0728	\N	0	2026-06-19 03:53:59.752054+05:30	\N	\N
4477	354	4346	nemotron-nano-9b-v2:free	191	\N	Nemotron Nano 9B V2 (free)	\N	0	2026-06-19 03:53:59.752789+05:30	\N	\N
4478	354	4351	qwen3-30b-a3b-thinking-2507	193	\N	Qwen3 30B A3B Thinking 2507	\N	0	2026-06-19 03:53:59.753716+05:30	\N	\N
4479	354	4377	deepseek-chat-v3.1	196	\N	DeepSeek V3.1	\N	0	2026-06-19 03:53:59.755727+05:30	\N	\N
4480	354	4366	mistral-medium-3.1	197	\N	Mistral Medium 3.1	\N	0	2026-06-19 03:53:59.758653+05:30	\N	\N
4481	354	4363	gpt-5-chat	200	\N	GPT-5 Chat	\N	0	2026-06-19 03:53:59.760854+05:30	\N	\N
4482	354	4363	gpt-5	201	\N	GPT-5	\N	0	2026-06-19 03:53:59.762928+05:30	\N	\N
4483	354	4363	gpt-5-mini	202	\N	GPT-5 Mini	\N	0	2026-06-19 03:53:59.765753+05:30	\N	\N
4484	354	4363	gpt-5-nano	203	\N	GPT-5 Nano	\N	0	2026-06-19 03:53:59.766608+05:30	\N	\N
4485	354	4363	gpt-oss-120b:free	204	\N	gpt-oss-120b (free)	\N	0	2026-06-19 03:53:59.768069+05:30	\N	\N
4486	354	4363	gpt-oss-120b	205	\N	gpt-oss-120b	\N	0	2026-06-19 03:53:59.770625+05:30	\N	\N
4487	354	4363	gpt-oss-20b:free	206	\N	gpt-oss-20b (free)	\N	0	2026-06-19 03:53:59.775264+05:30	\N	\N
4488	354	4363	gpt-oss-20b	207	\N	gpt-oss-20b	\N	0	2026-06-19 03:53:59.779402+05:30	\N	\N
4489	354	4343	claude-opus-4.1	208	\N	Claude Opus 4.1	\N	0	2026-06-19 03:53:59.782316+05:30	\N	\N
4490	354	4366	codestral-2508	209	\N	Codestral 2508	\N	0	2026-06-19 03:53:59.784794+05:30	\N	\N
4491	354	4351	qwen3-coder-30b-a3b-instruct	210	\N	Qwen3 Coder 30B A3B Instruct	\N	0	2026-06-19 03:53:59.788237+05:30	\N	\N
4492	354	4351	qwen3-30b-a3b-instruct-2507	211	\N	Qwen3 30B A3B Instruct 2507	\N	0	2026-06-19 03:53:59.789801+05:30	\N	\N
4493	354	4351	qwen3-235b-a22b-thinking-2507	214	\N	Qwen3 235B A22B Thinking 2507	\N	0	2026-06-19 03:53:59.794116+05:30	\N	\N
4494	354	4351	qwen3-coder:free	215	\N	Qwen3 Coder 480B A35B (free)	\N	0	2026-06-19 03:53:59.798912+05:30	\N	\N
4495	354	4351	qwen3-coder	216	\N	Qwen3 Coder 480B A35B	\N	0	2026-06-19 03:53:59.800187+05:30	\N	\N
4496	354	4336	gemini-2.5-flash-lite	218	\N	Gemini 2.5 Flash Lite	\N	0	2026-06-19 03:53:59.802833+05:30	\N	\N
4497	354	4351	qwen3-235b-a22b-2507	219	\N	Qwen3 235B A22B Instruct 2507	\N	0	2026-06-19 03:53:59.803999+05:30	\N	\N
4498	354	4366	mistral-small-3.2-24b-instruct	227	\N	Mistral Small 3.2 24B	\N	0	2026-06-19 03:53:59.805255+05:30	\N	\N
4499	354	4354	minimax-m1	228	\N	MiniMax M1	\N	0	2026-06-19 03:53:59.806472+05:30	\N	\N
4500	354	4336	gemini-2.5-flash	229	\N	Gemini 2.5 Flash	\N	0	2026-06-19 03:53:59.808577+05:30	\N	\N
4501	354	4336	gemini-2.5-pro	230	\N	Gemini 2.5 Pro	\N	0	2026-06-19 03:53:59.810447+05:30	\N	\N
4502	354	4363	o3-pro	231	\N	o3 Pro	\N	0	2026-06-19 03:53:59.811711+05:30	\N	\N
4503	354	4336	gemini-2.5-pro-preview	232	\N	Gemini 2.5 Pro Preview 06-05	\N	0	2026-06-19 03:53:59.814542+05:30	\N	\N
4504	354	4377	deepseek-r1-0528	233	\N	R1 0528	\N	0	2026-06-19 03:53:59.819009+05:30	\N	\N
4505	354	4343	claude-opus-4	234	\N	Claude Opus 4	\N	0	2026-06-19 03:53:59.823734+05:30	\N	\N
4506	354	4343	claude-sonnet-4	235	\N	Claude Sonnet 4	\N	0	2026-06-19 03:53:59.826433+05:30	\N	\N
4507	354	4336	gemma-3n-e4b-it	236	\N	Gemma 3n 4B	\N	0	2026-06-19 03:53:59.828191+05:30	\N	\N
4508	354	4366	mistral-medium-3	237	\N	Mistral Medium 3	\N	0	2026-06-19 03:53:59.830381+05:30	\N	\N
4509	354	4336	gemini-2.5-pro-preview-05-06	238	\N	Gemini 2.5 Pro Preview 05-06	\N	0	2026-06-19 03:53:59.831442+05:30	\N	\N
4510	353	\N	meta-llama	\N	\N	Meta	\N	0	2026-06-19 03:53:59.832946+05:30	\N	\N
4511	355	4510	meta-llama_url	\N	https://api.llama.api/v1/chat/completions	Meta URL	\N	0	2026-06-19 03:53:59.834586+05:30	\N	\N
4512	354	4510	llama-guard-4-12b	241	\N	Llama Guard 4 12B	\N	0	2026-06-19 03:53:59.839183+05:30	\N	\N
4513	354	4351	qwen3-30b-a3b	242	\N	Qwen3 30B A3B	\N	0	2026-06-19 03:53:59.840915+05:30	\N	\N
4514	354	4351	qwen3-8b	243	\N	Qwen3 8B	\N	0	2026-06-19 03:53:59.842353+05:30	\N	\N
4515	354	4351	qwen3-14b	244	\N	Qwen3 14B	\N	0	2026-06-19 03:53:59.844418+05:30	\N	\N
4516	354	4351	qwen3-32b	245	\N	Qwen3 32B	\N	0	2026-06-19 03:53:59.846629+05:30	\N	\N
4517	354	4351	qwen3-235b-a22b	246	\N	Qwen3 235B A22B	\N	0	2026-06-19 03:53:59.849776+05:30	\N	\N
4518	354	4363	o4-mini-high	247	\N	o4 Mini High	\N	0	2026-06-19 03:53:59.851812+05:30	\N	\N
4519	354	4363	o3	248	\N	o3	\N	0	2026-06-19 03:53:59.854643+05:30	\N	\N
4520	354	4363	o4-mini	249	\N	o4 Mini	\N	0	2026-06-19 03:53:59.856681+05:30	\N	\N
4521	354	4363	gpt-4.1	250	\N	GPT-4.1	\N	0	2026-06-19 03:53:59.857663+05:30	\N	\N
4522	354	4363	gpt-4.1-mini	251	\N	GPT-4.1 Mini	\N	0	2026-06-19 03:53:59.858741+05:30	\N	\N
4523	354	4363	gpt-4.1-nano	252	\N	GPT-4.1 Nano	\N	0	2026-06-19 03:53:59.860565+05:30	\N	\N
4524	354	4510	llama-4-maverick	253	\N	Llama 4 Maverick	\N	0	2026-06-19 03:53:59.861831+05:30	\N	\N
4525	354	4510	llama-4-scout	254	\N	Llama 4 Scout	\N	0	2026-06-19 03:53:59.863763+05:30	\N	\N
4526	354	4377	deepseek-chat-v3-0324	255	\N	DeepSeek V3 0324	\N	0	2026-06-19 03:53:59.865779+05:30	\N	\N
4527	354	4363	o1-pro	256	\N	o1-pro	\N	0	2026-06-19 03:53:59.866867+05:30	\N	\N
4528	354	4366	mistral-small-3.1-24b-instruct	257	\N	Mistral Small 3.1 24B	\N	0	2026-06-19 03:53:59.869024+05:30	\N	\N
4529	354	4336	gemma-3-4b-it	258	\N	Gemma 3 4B	\N	0	2026-06-19 03:53:59.870099+05:30	\N	\N
4530	354	4336	gemma-3-12b-it	259	\N	Gemma 3 12B	\N	0	2026-06-19 03:53:59.870911+05:30	\N	\N
4531	354	4340	command-a	260	\N	Command A	\N	0	2026-06-19 03:53:59.8731+05:30	\N	\N
4532	354	4363	gpt-4o-mini-search-preview	261	\N	GPT-4o-mini Search Preview	\N	0	2026-06-19 03:53:59.87553+05:30	\N	\N
4533	354	4363	gpt-4o-search-preview	262	\N	GPT-4o Search Preview	\N	0	2026-06-19 03:53:59.878513+05:30	\N	\N
4534	354	4336	gemma-3-27b-it	264	\N	Gemma 3 27B	\N	0	2026-06-19 03:53:59.88017+05:30	\N	\N
4535	354	4366	mistral-saba	269	\N	Saba	\N	0	2026-06-19 03:53:59.881398+05:30	\N	\N
4536	354	4363	o3-mini-high	270	\N	o3 Mini High	\N	0	2026-06-19 03:53:59.882562+05:30	\N	\N
4537	354	4351	qwen2.5-vl-72b-instruct	274	\N	Qwen2.5 VL 72B Instruct	\N	0	2026-06-19 03:53:59.883482+05:30	\N	\N
4538	354	4351	qwen-plus	275	\N	Qwen-Plus	\N	0	2026-06-19 03:53:59.884301+05:30	\N	\N
4539	354	4363	o3-mini	276	\N	o3 Mini	\N	0	2026-06-19 03:53:59.88543+05:30	\N	\N
4540	354	4366	mistral-small-24b-instruct-2501	277	\N	Mistral Small 3	\N	0	2026-06-19 03:53:59.887489+05:30	\N	\N
4541	354	4377	deepseek-r1-distill-llama-70b	279	\N	R1 Distill Llama 70B	\N	0	2026-06-19 03:53:59.889441+05:30	\N	\N
4542	354	4377	deepseek-r1	280	\N	R1	\N	0	2026-06-19 03:53:59.892318+05:30	\N	\N
4543	354	4354	minimax-01	281	\N	MiniMax-01	\N	0	2026-06-19 03:53:59.89416+05:30	\N	\N
4544	354	4377	deepseek-chat	284	\N	DeepSeek V3	\N	0	2026-06-19 03:53:59.896096+05:30	\N	\N
4545	354	4363	o1	286	\N	o1	\N	0	2026-06-19 03:53:59.899661+05:30	\N	\N
4546	354	4340	command-r7b-12-2024	287	\N	Command R7B (12-2024)	\N	0	2026-06-19 03:53:59.901344+05:30	\N	\N
4547	354	4510	llama-3.3-70b-instruct:free	288	\N	Llama 3.3 70B Instruct (free)	\N	0	2026-06-19 03:53:59.904006+05:30	\N	\N
4548	354	4510	llama-3.3-70b-instruct	289	\N	Llama 3.3 70B Instruct	\N	0	2026-06-19 03:53:59.905935+05:30	\N	\N
4549	354	4430	nova-lite-v1	290	\N	Nova Lite 1.0	\N	0	2026-06-19 03:53:59.912339+05:30	\N	\N
4550	354	4430	nova-micro-v1	291	\N	Nova Micro 1.0	\N	0	2026-06-19 03:53:59.918748+05:30	\N	\N
4551	354	4430	nova-pro-v1	292	\N	Nova Pro 1.0	\N	0	2026-06-19 03:53:59.924263+05:30	\N	\N
4552	354	4363	gpt-4o-2024-11-20	293	\N	GPT-4o (2024-11-20)	\N	0	2026-06-19 03:53:59.926273+05:30	\N	\N
4553	354	4366	mistral-large-2407	294	\N	Mistral Large 2407	\N	0	2026-06-19 03:53:59.928322+05:30	\N	\N
4554	354	4351	qwen-2.5-coder-32b-instruct	295	\N	Qwen2.5 Coder 32B Instruct	\N	0	2026-06-19 03:53:59.935518+05:30	\N	\N
4555	354	4343	claude-3.5-haiku	297	\N	Claude 3.5 Haiku	\N	0	2026-06-19 03:53:59.941948+05:30	\N	\N
4556	354	4351	qwen-2.5-7b-instruct	299	\N	Qwen2.5 7B Instruct	\N	0	2026-06-19 03:53:59.946073+05:30	\N	\N
4557	354	4510	llama-3.2-3b-instruct:free	303	\N	Llama 3.2 3B Instruct (free)	\N	0	2026-06-19 03:53:59.950286+05:30	\N	\N
4558	354	4510	llama-3.2-3b-instruct	304	\N	Llama 3.2 3B Instruct	\N	0	2026-06-19 03:53:59.953761+05:30	\N	\N
4559	354	4510	llama-3.2-1b-instruct	305	\N	Llama 3.2 1B Instruct	\N	0	2026-06-19 03:53:59.956153+05:30	\N	\N
4560	354	4510	llama-3.2-11b-vision-instruct	306	\N	Llama 3.2 11B Vision Instruct	\N	0	2026-06-19 03:53:59.959749+05:30	\N	\N
4561	354	4351	qwen-2.5-72b-instruct	307	\N	Qwen2.5 72B Instruct	\N	0	2026-06-19 03:53:59.962524+05:30	\N	\N
4562	354	4340	command-r-plus-08-2024	308	\N	Command R+ (08-2024)	\N	0	2026-06-19 03:53:59.965492+05:30	\N	\N
4563	354	4340	command-r-08-2024	309	\N	Command R (08-2024)	\N	0	2026-06-19 03:53:59.967869+05:30	\N	\N
4564	354	4363	gpt-4o-2024-08-06	315	\N	GPT-4o (2024-08-06)	\N	0	2026-06-19 03:53:59.971059+05:30	\N	\N
4565	354	4510	llama-3.1-8b-instruct	316	\N	Llama 3.1 8B Instruct	\N	0	2026-06-19 03:53:59.973913+05:30	\N	\N
4566	354	4510	llama-3.1-70b-instruct	317	\N	Llama 3.1 70B Instruct	\N	0	2026-06-19 03:53:59.976908+05:30	\N	\N
4567	354	4366	mistral-nemo	318	\N	Mistral Nemo	\N	0	2026-06-19 03:53:59.980456+05:30	\N	\N
4568	354	4363	gpt-4o-mini-2024-07-18	319	\N	GPT-4o-mini (2024-07-18)	\N	0	2026-06-19 03:53:59.982862+05:30	\N	\N
4569	354	4363	gpt-4o-mini	320	\N	GPT-4o-mini	\N	0	2026-06-19 03:53:59.985224+05:30	\N	\N
4570	354	4336	gemma-2-27b-it	321	\N	Gemma 2 27B	\N	0	2026-06-19 03:53:59.988837+05:30	\N	\N
4571	354	4363	gpt-4o-2024-05-13	322	\N	GPT-4o (2024-05-13)	\N	0	2026-06-19 03:53:59.991793+05:30	\N	\N
4572	354	4363	gpt-4o	323	\N	GPT-4o	\N	0	2026-06-19 03:53:59.995193+05:30	\N	\N
4573	354	4510	llama-3-8b-instruct	324	\N	Llama 3 8B Instruct	\N	0	2026-06-19 03:53:59.996841+05:30	\N	\N
4574	354	4510	llama-3-70b-instruct	325	\N	Llama 3 70B Instruct	\N	0	2026-06-19 03:54:00.002225+05:30	\N	\N
4575	354	4366	mixtral-8x22b-instruct	326	\N	Mixtral 8x22B Instruct	\N	0	2026-06-19 03:54:00.007127+05:30	\N	\N
4576	354	4363	gpt-4-turbo	328	\N	GPT-4 Turbo	\N	0	2026-06-19 03:54:00.010426+05:30	\N	\N
4577	354	4343	claude-3-haiku	329	\N	Claude 3 Haiku	\N	0	2026-06-19 03:54:00.019111+05:30	\N	\N
4578	354	4366	mistral-large	330	\N	Mistral Large	\N	0	2026-06-19 03:54:00.024571+05:30	\N	\N
4579	354	4363	gpt-4-turbo-preview	331	\N	GPT-4 Turbo Preview	\N	0	2026-06-19 03:54:00.067478+05:30	\N	\N
4580	354	4363	gpt-3.5-turbo-0613	332	\N	GPT-3.5 Turbo (older v0613)	\N	0	2026-06-19 03:54:00.077456+05:30	\N	\N
4581	354	4363	gpt-3.5-turbo-instruct	334	\N	GPT-3.5 Turbo Instruct	\N	0	2026-06-19 03:54:00.07902+05:30	\N	\N
4582	354	4363	gpt-3.5-turbo-16k	335	\N	GPT-3.5 Turbo 16k	\N	0	2026-06-19 03:54:00.080429+05:30	\N	\N
4583	354	4363	gpt-4	339	\N	GPT-4	\N	0	2026-06-19 03:54:00.084112+05:30	\N	\N
4584	354	4363	gpt-3.5-turbo	340	\N	GPT-3.5 Turbo	\N	0	2026-06-19 03:54:00.091035+05:30	\N	\N
4585	353	\N	openrouter	\N	\N	OpenRouter	\N	0	2026-06-19 03:54:00.094302+05:30	\N	\N
4586	355	4585	openrouter_url	\N	https://openrouter.ai/api/v1/chat/completions	OpenRouter URL	\N	0	2026-06-19 03:54:00.098273+05:30	\N	\N
4587	354	4585	google/gemini-3.1-flash-image	0	\N	Google: Nano Banana 2 (Gemini 3.1 Flash Image)	\N	0	2026-06-19 03:54:00.127847+05:30	\N	\N
4588	354	4585	google/gemini-3-pro-image	1	\N	Google: Nano Banana Pro (Gemini 3 Pro Image)	\N	0	2026-06-19 03:54:00.146864+05:30	\N	\N
4589	354	4585	cohere/north-mini-code:free	2	\N	Cohere: North Mini Code (free)	\N	0	2026-06-19 03:54:00.150117+05:30	\N	\N
4590	354	4585	anthropic/claude-fable-5	7	\N	Anthropic: Claude Fable 5	\N	0	2026-06-19 03:54:00.154465+05:30	\N	\N
4591	354	4585	nvidia/nemotron-3.5-content-safety:free	9	\N	NVIDIA: Nemotron 3.5 Content Safety (free)	\N	0	2026-06-19 03:54:00.158862+05:30	\N	\N
4592	354	4585	nvidia/nemotron-3-ultra-550b-a55b:free	10	\N	NVIDIA: Nemotron 3 Ultra (free)	\N	0	2026-06-19 03:54:00.163184+05:30	\N	\N
4593	354	4585	nvidia/nemotron-3-ultra-550b-a55b	11	\N	NVIDIA: Nemotron 3 Ultra	\N	0	2026-06-19 03:54:00.166894+05:30	\N	\N
4594	354	4585	qwen/qwen3.7-plus	12	\N	Qwen: Qwen3.7 Plus	\N	0	2026-06-19 03:54:00.177714+05:30	\N	\N
4595	354	4585	minimax/minimax-m3	13	\N	MiniMax: MiniMax M3	\N	0	2026-06-19 03:54:00.180945+05:30	\N	\N
4596	354	4585	anthropic/claude-opus-4.8-fast	15	\N	Anthropic: Claude Opus 4.8 (Fast)	\N	0	2026-06-19 03:54:00.183611+05:30	\N	\N
4597	354	4585	anthropic/claude-opus-4.8	16	\N	Anthropic: Claude Opus 4.8	\N	0	2026-06-19 03:54:00.185634+05:30	\N	\N
4598	354	4585	qwen/qwen3.7-max	17	\N	Qwen: Qwen3.7 Max	\N	0	2026-06-19 03:54:00.188264+05:30	\N	\N
4599	354	4585	google/gemini-3.5-flash	19	\N	Google: Gemini 3.5 Flash	\N	0	2026-06-19 03:54:00.196433+05:30	\N	\N
4600	354	4585	anthropic/claude-opus-4.7-fast	20	\N	Anthropic: Claude Opus 4.7 (Fast)	\N	0	2026-06-19 03:54:00.198807+05:30	\N	\N
4601	354	4585	google/gemini-3.1-flash-lite	23	\N	Google: Gemini 3.1 Flash Lite	\N	0	2026-06-19 03:54:00.206143+05:30	\N	\N
4602	354	4585	openai/gpt-chat-latest	24	\N	OpenAI: GPT Chat Latest	\N	0	2026-06-19 03:54:00.210492+05:30	\N	\N
4603	354	4585	mistralai/mistral-medium-3-5	27	\N	Mistral: Mistral Medium 3.5	\N	0	2026-06-19 03:54:00.21386+05:30	\N	\N
4604	354	4585	nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free	29	\N	NVIDIA: Nemotron 3 Nano Omni (free)	\N	0	2026-06-19 03:54:00.218479+05:30	\N	\N
4605	354	4585	qwen/qwen3.5-plus-20260420	41	\N	Qwen: Qwen3.5 Plus 2026-04-20	\N	0	2026-06-19 03:54:00.220456+05:30	\N	\N
4606	354	4585	qwen/qwen3.6-flash	42	\N	Qwen: Qwen3.6 Flash	\N	0	2026-06-19 03:54:00.22361+05:30	\N	\N
4607	354	4585	qwen/qwen3.6-35b-a3b	43	\N	Qwen: Qwen3.6 35B A3B	\N	0	2026-06-19 03:54:00.231347+05:30	\N	\N
4608	354	4585	qwen/qwen3.6-max-preview	44	\N	Qwen: Qwen3.6 Max Preview	\N	0	2026-06-19 03:54:00.247362+05:30	\N	\N
4609	354	4585	qwen/qwen3.6-27b	45	\N	Qwen: Qwen3.6 27B	\N	0	2026-06-19 03:54:00.25512+05:30	\N	\N
4610	354	4585	openai/gpt-5.5-pro	46	\N	OpenAI: GPT-5.5 Pro	\N	0	2026-06-19 03:54:00.258216+05:30	\N	\N
4611	354	4585	openai/gpt-5.5	47	\N	OpenAI: GPT-5.5	\N	0	2026-06-19 03:54:00.261781+05:30	\N	\N
4612	354	4585	deepseek/deepseek-v4-pro	48	\N	DeepSeek: DeepSeek V4 Pro	\N	0	2026-06-19 03:54:00.264538+05:30	\N	\N
4613	354	4585	deepseek/deepseek-v4-flash	49	\N	DeepSeek: DeepSeek V4 Flash	\N	0	2026-06-19 03:54:00.269211+05:30	\N	\N
4614	354	4585	openai/gpt-5.4-image-2	54	\N	OpenAI: GPT-5.4 Image 2	\N	0	2026-06-19 03:54:00.273933+05:30	\N	\N
4615	354	4585	anthropic/claude-opus-4.7	59	\N	Anthropic: Claude Opus 4.7	\N	0	2026-06-19 03:54:00.280762+05:30	\N	\N
4616	354	4585	anthropic/claude-opus-4.6-fast	60	\N	Anthropic: Claude Opus 4.6 (Fast)	\N	0	2026-06-19 03:54:00.28364+05:30	\N	\N
4617	354	4585	google/gemma-4-26b-a4b-it:free	62	\N	Google: Gemma 4 26B A4B  (free)	\N	0	2026-06-19 03:54:00.286823+05:30	\N	\N
4618	354	4585	google/gemma-4-26b-a4b-it	63	\N	Google: Gemma 4 26B A4B 	\N	0	2026-06-19 03:54:00.289786+05:30	\N	\N
4619	354	4585	google/gemma-4-31b-it:free	64	\N	Google: Gemma 4 31B (free)	\N	0	2026-06-19 03:54:00.292387+05:30	\N	\N
4620	354	4585	google/gemma-4-31b-it	65	\N	Google: Gemma 4 31B	\N	0	2026-06-19 03:54:00.296661+05:30	\N	\N
4621	354	4585	qwen/qwen3.6-plus	66	\N	Qwen: Qwen3.6 Plus	\N	0	2026-06-19 03:54:00.317999+05:30	\N	\N
4622	354	4585	google/lyria-3-pro-preview	70	\N	Google: Lyria 3 Pro Preview	\N	0	2026-06-19 03:54:00.337692+05:30	\N	\N
4623	354	4585	google/lyria-3-clip-preview	71	\N	Google: Lyria 3 Clip Preview	\N	0	2026-06-19 03:54:00.340484+05:30	\N	\N
4624	354	4585	minimax/minimax-m2.7	74	\N	MiniMax: MiniMax M2.7	\N	0	2026-06-19 03:54:00.346288+05:30	\N	\N
4625	354	4585	openai/gpt-5.4-nano	75	\N	OpenAI: GPT-5.4 Nano	\N	0	2026-06-19 03:54:00.351482+05:30	\N	\N
4626	354	4585	openai/gpt-5.4-mini	76	\N	OpenAI: GPT-5.4 Mini	\N	0	2026-06-19 03:54:00.354469+05:30	\N	\N
4627	354	4585	mistralai/mistral-small-2603	77	\N	Mistral: Mistral Small 4	\N	0	2026-06-19 03:54:00.357052+05:30	\N	\N
4628	354	4585	nvidia/nemotron-3-super-120b-a12b:free	79	\N	NVIDIA: Nemotron 3 Super (free)	\N	0	2026-06-19 03:54:00.361146+05:30	\N	\N
4629	354	4585	nvidia/nemotron-3-super-120b-a12b	80	\N	NVIDIA: Nemotron 3 Super	\N	0	2026-06-19 03:54:00.36488+05:30	\N	\N
4630	354	4585	qwen/qwen3.5-9b	82	\N	Qwen: Qwen3.5-9B	\N	0	2026-06-19 03:54:00.366728+05:30	\N	\N
4631	354	4585	openai/gpt-5.4-pro	83	\N	OpenAI: GPT-5.4 Pro	\N	0	2026-06-19 03:54:00.369098+05:30	\N	\N
4632	354	4585	openai/gpt-5.4	84	\N	OpenAI: GPT-5.4	\N	0	2026-06-19 03:54:00.372264+05:30	\N	\N
4633	354	4585	openai/gpt-5.3-chat	86	\N	OpenAI: GPT-5.3 Chat	\N	0	2026-06-19 03:54:00.376244+05:30	\N	\N
4634	354	4585	google/gemini-3.1-flash-lite-preview	87	\N	Google: Gemini 3.1 Flash Lite Preview	\N	0	2026-06-19 03:54:00.382886+05:30	\N	\N
4635	354	4585	google/gemini-3.1-flash-image-preview	89	\N	Google: Nano Banana 2 (Gemini 3.1 Flash Image Preview)	\N	0	2026-06-19 03:54:00.388022+05:30	\N	\N
4636	354	4585	qwen/qwen3.5-35b-a3b	90	\N	Qwen: Qwen3.5-35B-A3B	\N	0	2026-06-19 03:54:00.390862+05:30	\N	\N
4637	354	4585	qwen/qwen3.5-27b	91	\N	Qwen: Qwen3.5-27B	\N	0	2026-06-19 03:54:00.392913+05:30	\N	\N
4638	354	4585	qwen/qwen3.5-122b-a10b	92	\N	Qwen: Qwen3.5-122B-A10B	\N	0	2026-06-19 03:54:00.396039+05:30	\N	\N
4639	354	4585	qwen/qwen3.5-flash-02-23	93	\N	Qwen: Qwen3.5-Flash	\N	0	2026-06-19 03:54:00.397897+05:30	\N	\N
4640	354	4585	google/gemini-3.1-pro-preview-customtools	95	\N	Google: Gemini 3.1 Pro Preview Custom Tools	\N	0	2026-06-19 03:54:00.400949+05:30	\N	\N
4641	354	4585	openai/gpt-5.3-codex	96	\N	OpenAI: GPT-5.3-Codex	\N	0	2026-06-19 03:54:00.405137+05:30	\N	\N
4642	354	4585	google/gemini-3.1-pro-preview	98	\N	Google: Gemini 3.1 Pro Preview	\N	0	2026-06-19 03:54:00.406387+05:30	\N	\N
4643	354	4585	anthropic/claude-sonnet-4.6	99	\N	Anthropic: Claude Sonnet 4.6	\N	0	2026-06-19 03:54:00.411657+05:30	\N	\N
4644	354	4585	qwen/qwen3.5-plus-02-15	100	\N	Qwen: Qwen3.5 Plus 2026-02-15	\N	0	2026-06-19 03:54:00.41731+05:30	\N	\N
4645	354	4585	qwen/qwen3.5-397b-a17b	101	\N	Qwen: Qwen3.5 397B A17B	\N	0	2026-06-19 03:54:00.421271+05:30	\N	\N
4646	354	4585	minimax/minimax-m2.5	102	\N	MiniMax: MiniMax M2.5	\N	0	2026-06-19 03:54:00.424613+05:30	\N	\N
4647	354	4585	qwen/qwen3-max-thinking	104	\N	Qwen: Qwen3 Max Thinking	\N	0	2026-06-19 03:54:00.427335+05:30	\N	\N
4648	354	4585	anthropic/claude-opus-4.6	105	\N	Anthropic: Claude Opus 4.6	\N	0	2026-06-19 03:54:00.430271+05:30	\N	\N
4649	354	4585	qwen/qwen3-coder-next	106	\N	Qwen: Qwen3 Coder Next	\N	0	2026-06-19 03:54:00.432573+05:30	\N	\N
4650	354	4585	minimax/minimax-m2-her	111	\N	MiniMax: MiniMax M2-her	\N	0	2026-06-19 03:54:00.437162+05:30	\N	\N
4651	354	4585	openai/gpt-audio	115	\N	OpenAI: GPT Audio	\N	0	2026-06-19 03:54:00.44232+05:30	\N	\N
4652	354	4585	openai/gpt-audio-mini	116	\N	OpenAI: GPT Audio Mini	\N	0	2026-06-19 03:54:00.44487+05:30	\N	\N
4653	354	4585	openai/gpt-5.2-codex	118	\N	OpenAI: GPT-5.2-Codex	\N	0	2026-06-19 03:54:00.447635+05:30	\N	\N
4654	354	4585	minimax/minimax-m2.1	121	\N	MiniMax: MiniMax M2.1	\N	0	2026-06-19 03:54:00.452642+05:30	\N	\N
4655	354	4585	google/gemini-3-flash-preview	123	\N	Google: Gemini 3 Flash Preview	\N	0	2026-06-19 03:54:00.456664+05:30	\N	\N
4656	354	4585	nvidia/nemotron-3-nano-30b-a3b:free	124	\N	NVIDIA: Nemotron 3 Nano 30B A3B (free)	\N	0	2026-06-19 03:54:00.461336+05:30	\N	\N
4657	354	4585	nvidia/nemotron-3-nano-30b-a3b	125	\N	NVIDIA: Nemotron 3 Nano 30B A3B	\N	0	2026-06-19 03:54:00.467473+05:30	\N	\N
4658	354	4585	openai/gpt-5.2-chat	126	\N	OpenAI: GPT-5.2 Chat	\N	0	2026-06-19 03:54:00.471221+05:30	\N	\N
4659	354	4585	openai/gpt-5.2-pro	127	\N	OpenAI: GPT-5.2 Pro	\N	0	2026-06-19 03:54:00.47342+05:30	\N	\N
4660	354	4585	openai/gpt-5.2	128	\N	OpenAI: GPT-5.2	\N	0	2026-06-19 03:54:00.478626+05:30	\N	\N
4661	354	4585	mistralai/devstral-2512	129	\N	Mistral: Devstral 2 2512	\N	0	2026-06-19 03:54:00.481012+05:30	\N	\N
4662	354	4585	openai/gpt-5.1-codex-max	134	\N	OpenAI: GPT-5.1-Codex-Max	\N	0	2026-06-19 03:54:00.483544+05:30	\N	\N
4663	354	4585	amazon/nova-2-lite-v1	135	\N	Amazon: Nova 2 Lite	\N	0	2026-06-19 03:54:00.487271+05:30	\N	\N
4664	354	4585	mistralai/ministral-14b-2512	136	\N	Mistral: Ministral 3 14B 2512	\N	0	2026-06-19 03:54:00.491237+05:30	\N	\N
4665	354	4585	mistralai/ministral-8b-2512	137	\N	Mistral: Ministral 3 8B 2512	\N	0	2026-06-19 03:54:00.493365+05:30	\N	\N
4666	354	4585	mistralai/ministral-3b-2512	138	\N	Mistral: Ministral 3 3B 2512	\N	0	2026-06-19 03:54:00.496469+05:30	\N	\N
4667	354	4585	mistralai/mistral-large-2512	139	\N	Mistral: Mistral Large 3 2512	\N	0	2026-06-19 03:54:00.499647+05:30	\N	\N
4668	354	4585	deepseek/deepseek-v3.2	141	\N	DeepSeek: DeepSeek V3.2	\N	0	2026-06-19 03:54:00.502028+05:30	\N	\N
4669	354	4585	anthropic/claude-opus-4.5	143	\N	Anthropic: Claude Opus 4.5	\N	0	2026-06-19 03:54:00.505535+05:30	\N	\N
4670	354	4585	google/gemini-3-pro-image-preview	145	\N	Google: Nano Banana Pro (Gemini 3 Pro Image Preview)	\N	0	2026-06-19 03:54:00.510548+05:30	\N	\N
4671	354	4585	openai/gpt-5.1	147	\N	OpenAI: GPT-5.1	\N	0	2026-06-19 03:54:00.514758+05:30	\N	\N
4672	354	4585	openai/gpt-5.1-chat	148	\N	OpenAI: GPT-5.1 Chat	\N	0	2026-06-19 03:54:00.519959+05:30	\N	\N
4673	354	4585	openai/gpt-5.1-codex	149	\N	OpenAI: GPT-5.1-Codex	\N	0	2026-06-19 03:54:00.533739+05:30	\N	\N
4674	354	4585	openai/gpt-5.1-codex-mini	150	\N	OpenAI: GPT-5.1-Codex-Mini	\N	0	2026-06-19 03:54:00.549236+05:30	\N	\N
4675	354	4585	amazon/nova-premier-v1	152	\N	Amazon: Nova Premier 1.0	\N	0	2026-06-19 03:54:00.554229+05:30	\N	\N
4676	354	4585	mistralai/voxtral-small-24b-2507	154	\N	Mistral: Voxtral Small 24B 2507	\N	0	2026-06-19 03:54:00.560269+05:30	\N	\N
4677	354	4585	openai/gpt-oss-safeguard-20b	155	\N	OpenAI: gpt-oss-safeguard-20b	\N	0	2026-06-19 03:54:00.56388+05:30	\N	\N
4678	354	4585	nvidia/nemotron-nano-12b-v2-vl:free	156	\N	NVIDIA: Nemotron Nano 12B 2 VL (free)	\N	0	2026-06-19 03:54:00.569088+05:30	\N	\N
4679	354	4585	minimax/minimax-m2	157	\N	MiniMax: MiniMax M2	\N	0	2026-06-19 03:54:00.574673+05:30	\N	\N
4680	354	4585	qwen/qwen3-vl-32b-instruct	158	\N	Qwen: Qwen3 VL 32B Instruct	\N	0	2026-06-19 03:54:00.58151+05:30	\N	\N
4681	354	4585	openai/gpt-5-image-mini	161	\N	OpenAI: GPT-5 Image Mini	\N	0	2026-06-19 03:54:00.584214+05:30	\N	\N
4682	354	4585	anthropic/claude-haiku-4.5	162	\N	Anthropic: Claude Haiku 4.5	\N	0	2026-06-19 03:54:00.58846+05:30	\N	\N
4683	354	4585	qwen/qwen3-vl-8b-thinking	163	\N	Qwen: Qwen3 VL 8B Thinking	\N	0	2026-06-19 03:54:00.614404+05:30	\N	\N
4684	354	4585	qwen/qwen3-vl-8b-instruct	164	\N	Qwen: Qwen3 VL 8B Instruct	\N	0	2026-06-19 03:54:00.61933+05:30	\N	\N
4685	354	4585	openai/gpt-5-image	165	\N	OpenAI: GPT-5 Image	\N	0	2026-06-19 03:54:00.622325+05:30	\N	\N
4686	354	4585	openai/o3-deep-research	166	\N	OpenAI: o3 Deep Research	\N	0	2026-06-19 03:54:00.625626+05:30	\N	\N
4687	354	4585	openai/o4-mini-deep-research	167	\N	OpenAI: o4 Mini Deep Research	\N	0	2026-06-19 03:54:00.631276+05:30	\N	\N
4688	354	4585	nvidia/llama-3.3-nemotron-super-49b-v1.5	168	\N	NVIDIA: Llama 3.3 Nemotron Super 49B V1.5	\N	0	2026-06-19 03:54:00.647639+05:30	\N	\N
4689	354	4585	google/gemini-2.5-flash-image	169	\N	Google: Nano Banana (Gemini 2.5 Flash Image)	\N	0	2026-06-19 03:54:00.651839+05:30	\N	\N
4690	354	4585	qwen/qwen3-vl-30b-a3b-thinking	170	\N	Qwen: Qwen3 VL 30B A3B Thinking	\N	0	2026-06-19 03:54:00.656378+05:30	\N	\N
4691	354	4585	qwen/qwen3-vl-30b-a3b-instruct	171	\N	Qwen: Qwen3 VL 30B A3B Instruct	\N	0	2026-06-19 03:54:00.6593+05:30	\N	\N
4692	354	4585	openai/gpt-5-pro	172	\N	OpenAI: GPT-5 Pro	\N	0	2026-06-19 03:54:00.662306+05:30	\N	\N
4693	354	4585	anthropic/claude-sonnet-4.5	174	\N	Anthropic: Claude Sonnet 4.5	\N	0	2026-06-19 03:54:00.66456+05:30	\N	\N
4694	354	4585	deepseek/deepseek-v3.2-exp	175	\N	DeepSeek: DeepSeek V3.2 Exp	\N	0	2026-06-19 03:54:00.667944+05:30	\N	\N
4695	354	4585	google/gemini-2.5-flash-lite-preview-09-2025	178	\N	Google: Gemini 2.5 Flash Lite Preview 09-2025	\N	0	2026-06-19 03:54:00.669667+05:30	\N	\N
4696	354	4585	qwen/qwen3-vl-235b-a22b-thinking	179	\N	Qwen: Qwen3 VL 235B A22B Thinking	\N	0	2026-06-19 03:54:00.674889+05:30	\N	\N
4697	354	4585	qwen/qwen3-vl-235b-a22b-instruct	180	\N	Qwen: Qwen3 VL 235B A22B Instruct	\N	0	2026-06-19 03:54:00.68557+05:30	\N	\N
4698	354	4585	qwen/qwen3-max	181	\N	Qwen: Qwen3 Max	\N	0	2026-06-19 03:54:00.694515+05:30	\N	\N
4699	354	4585	qwen/qwen3-coder-plus	182	\N	Qwen: Qwen3 Coder Plus	\N	0	2026-06-19 03:54:00.70084+05:30	\N	\N
4700	354	4585	openai/gpt-5-codex	183	\N	OpenAI: GPT-5 Codex	\N	0	2026-06-19 03:54:00.702324+05:30	\N	\N
4701	354	4585	deepseek/deepseek-v3.1-terminus	184	\N	DeepSeek: DeepSeek V3.1 Terminus	\N	0	2026-06-19 03:54:00.704527+05:30	\N	\N
4702	354	4585	qwen/qwen3-coder-flash	185	\N	Qwen: Qwen3 Coder Flash	\N	0	2026-06-19 03:54:00.70653+05:30	\N	\N
4703	354	4585	qwen/qwen3-next-80b-a3b-thinking	186	\N	Qwen: Qwen3 Next 80B A3B Thinking	\N	0	2026-06-19 03:54:00.707656+05:30	\N	\N
4704	354	4585	qwen/qwen3-next-80b-a3b-instruct:free	187	\N	Qwen: Qwen3 Next 80B A3B Instruct (free)	\N	0	2026-06-19 03:54:00.708673+05:30	\N	\N
4705	354	4585	qwen/qwen3-next-80b-a3b-instruct	188	\N	Qwen: Qwen3 Next 80B A3B Instruct	\N	0	2026-06-19 03:54:00.709889+05:30	\N	\N
4706	354	4585	qwen/qwen-plus-2025-07-28:thinking	189	\N	Qwen: Qwen Plus 0728 (thinking)	\N	0	2026-06-19 03:54:00.722317+05:30	\N	\N
4707	354	4585	qwen/qwen-plus-2025-07-28	190	\N	Qwen: Qwen Plus 0728	\N	0	2026-06-19 03:54:00.724856+05:30	\N	\N
4708	354	4585	nvidia/nemotron-nano-9b-v2:free	191	\N	NVIDIA: Nemotron Nano 9B V2 (free)	\N	0	2026-06-19 03:54:00.728535+05:30	\N	\N
4709	354	4585	qwen/qwen3-30b-a3b-thinking-2507	193	\N	Qwen: Qwen3 30B A3B Thinking 2507	\N	0	2026-06-19 03:54:00.73308+05:30	\N	\N
4710	354	4585	deepseek/deepseek-chat-v3.1	196	\N	DeepSeek: DeepSeek V3.1	\N	0	2026-06-19 03:54:00.737416+05:30	\N	\N
4711	354	4585	mistralai/mistral-medium-3.1	197	\N	Mistral: Mistral Medium 3.1	\N	0	2026-06-19 03:54:00.740472+05:30	\N	\N
4712	354	4585	openai/gpt-5-chat	200	\N	OpenAI: GPT-5 Chat	\N	0	2026-06-19 03:54:00.748038+05:30	\N	\N
4713	354	4585	openai/gpt-5	201	\N	OpenAI: GPT-5	\N	0	2026-06-19 03:54:00.755212+05:30	\N	\N
4714	354	4585	openai/gpt-5-mini	202	\N	OpenAI: GPT-5 Mini	\N	0	2026-06-19 03:54:00.757315+05:30	\N	\N
4715	354	4585	openai/gpt-5-nano	203	\N	OpenAI: GPT-5 Nano	\N	0	2026-06-19 03:54:00.760678+05:30	\N	\N
4716	354	4585	openai/gpt-oss-120b:free	204	\N	OpenAI: gpt-oss-120b (free)	\N	0	2026-06-19 03:54:00.763463+05:30	\N	\N
4717	354	4585	openai/gpt-oss-120b	205	\N	OpenAI: gpt-oss-120b	\N	0	2026-06-19 03:54:00.766777+05:30	\N	\N
4718	354	4585	openai/gpt-oss-20b:free	206	\N	OpenAI: gpt-oss-20b (free)	\N	0	2026-06-19 03:54:00.771491+05:30	\N	\N
4719	354	4585	openai/gpt-oss-20b	207	\N	OpenAI: gpt-oss-20b	\N	0	2026-06-19 03:54:00.777963+05:30	\N	\N
4720	354	4585	anthropic/claude-opus-4.1	208	\N	Anthropic: Claude Opus 4.1	\N	0	2026-06-19 03:54:00.807854+05:30	\N	\N
4721	354	4585	mistralai/codestral-2508	209	\N	Mistral: Codestral 2508	\N	0	2026-06-19 03:54:00.814395+05:30	\N	\N
4722	354	4585	qwen/qwen3-coder-30b-a3b-instruct	210	\N	Qwen: Qwen3 Coder 30B A3B Instruct	\N	0	2026-06-19 03:54:00.816303+05:30	\N	\N
4723	354	4585	qwen/qwen3-30b-a3b-instruct-2507	211	\N	Qwen: Qwen3 30B A3B Instruct 2507	\N	0	2026-06-19 03:54:00.818088+05:30	\N	\N
4724	354	4585	qwen/qwen3-235b-a22b-thinking-2507	214	\N	Qwen: Qwen3 235B A22B Thinking 2507	\N	0	2026-06-19 03:54:00.830652+05:30	\N	\N
4725	354	4585	qwen/qwen3-coder:free	215	\N	Qwen: Qwen3 Coder 480B A35B (free)	\N	0	2026-06-19 03:54:00.835129+05:30	\N	\N
4726	354	4585	qwen/qwen3-coder	216	\N	Qwen: Qwen3 Coder 480B A35B	\N	0	2026-06-19 03:54:00.83728+05:30	\N	\N
4727	354	4585	google/gemini-2.5-flash-lite	218	\N	Google: Gemini 2.5 Flash Lite	\N	0	2026-06-19 03:54:00.847574+05:30	\N	\N
4728	354	4585	qwen/qwen3-235b-a22b-2507	219	\N	Qwen: Qwen3 235B A22B Instruct 2507	\N	0	2026-06-19 03:54:00.868458+05:30	\N	\N
4729	354	4585	mistralai/mistral-small-3.2-24b-instruct	227	\N	Mistral: Mistral Small 3.2 24B	\N	0	2026-06-19 03:54:00.871551+05:30	\N	\N
4730	354	4585	minimax/minimax-m1	228	\N	MiniMax: MiniMax M1	\N	0	2026-06-19 03:54:00.887097+05:30	\N	\N
4731	354	4585	google/gemini-2.5-flash	229	\N	Google: Gemini 2.5 Flash	\N	0	2026-06-19 03:54:00.89369+05:30	\N	\N
4732	354	4585	google/gemini-2.5-pro	230	\N	Google: Gemini 2.5 Pro	\N	0	2026-06-19 03:54:00.895343+05:30	\N	\N
4733	354	4585	openai/o3-pro	231	\N	OpenAI: o3 Pro	\N	0	2026-06-19 03:54:00.896602+05:30	\N	\N
4734	354	4585	google/gemini-2.5-pro-preview	232	\N	Google: Gemini 2.5 Pro Preview 06-05	\N	0	2026-06-19 03:54:00.898506+05:30	\N	\N
4735	354	4585	deepseek/deepseek-r1-0528	233	\N	DeepSeek: R1 0528	\N	0	2026-06-19 03:54:00.901306+05:30	\N	\N
4736	354	4585	anthropic/claude-opus-4	234	\N	Anthropic: Claude Opus 4	\N	0	2026-06-19 03:54:00.906891+05:30	\N	\N
4737	354	4585	anthropic/claude-sonnet-4	235	\N	Anthropic: Claude Sonnet 4	\N	0	2026-06-19 03:54:00.912957+05:30	\N	\N
4738	354	4585	google/gemma-3n-e4b-it	236	\N	Google: Gemma 3n 4B	\N	0	2026-06-19 03:54:00.916216+05:30	\N	\N
4739	354	4585	mistralai/mistral-medium-3	237	\N	Mistral: Mistral Medium 3	\N	0	2026-06-19 03:54:00.920222+05:30	\N	\N
4740	354	4585	google/gemini-2.5-pro-preview-05-06	238	\N	Google: Gemini 2.5 Pro Preview 05-06	\N	0	2026-06-19 03:54:00.922602+05:30	\N	\N
4741	354	4585	meta-llama/llama-guard-4-12b	241	\N	Meta: Llama Guard 4 12B	\N	0	2026-06-19 03:54:00.926401+05:30	\N	\N
4742	354	4585	qwen/qwen3-30b-a3b	242	\N	Qwen: Qwen3 30B A3B	\N	0	2026-06-19 03:54:00.988845+05:30	\N	\N
4743	354	4585	qwen/qwen3-8b	243	\N	Qwen: Qwen3 8B	\N	0	2026-06-19 03:54:00.998197+05:30	\N	\N
4744	354	4585	qwen/qwen3-14b	244	\N	Qwen: Qwen3 14B	\N	0	2026-06-19 03:54:01.016681+05:30	\N	\N
4745	354	4585	qwen/qwen3-32b	245	\N	Qwen: Qwen3 32B	\N	0	2026-06-19 03:54:01.02405+05:30	\N	\N
4746	354	4585	qwen/qwen3-235b-a22b	246	\N	Qwen: Qwen3 235B A22B	\N	0	2026-06-19 03:54:01.026248+05:30	\N	\N
4747	354	4585	openai/o4-mini-high	247	\N	OpenAI: o4 Mini High	\N	0	2026-06-19 03:54:01.028804+05:30	\N	\N
4748	354	4585	openai/o3	248	\N	OpenAI: o3	\N	0	2026-06-19 03:54:01.031805+05:30	\N	\N
4749	354	4585	openai/o4-mini	249	\N	OpenAI: o4 Mini	\N	0	2026-06-19 03:54:01.035189+05:30	\N	\N
4750	354	4585	openai/gpt-4.1	250	\N	OpenAI: GPT-4.1	\N	0	2026-06-19 03:54:01.037263+05:30	\N	\N
4751	354	4585	openai/gpt-4.1-mini	251	\N	OpenAI: GPT-4.1 Mini	\N	0	2026-06-19 03:54:01.046439+05:30	\N	\N
4752	354	4585	openai/gpt-4.1-nano	252	\N	OpenAI: GPT-4.1 Nano	\N	0	2026-06-19 03:54:01.054516+05:30	\N	\N
4753	354	4585	meta-llama/llama-4-maverick	253	\N	Meta: Llama 4 Maverick	\N	0	2026-06-19 03:54:01.058069+05:30	\N	\N
4754	354	4585	meta-llama/llama-4-scout	254	\N	Meta: Llama 4 Scout	\N	0	2026-06-19 03:54:01.060557+05:30	\N	\N
4755	354	4585	deepseek/deepseek-chat-v3-0324	255	\N	DeepSeek: DeepSeek V3 0324	\N	0	2026-06-19 03:54:01.063414+05:30	\N	\N
4756	354	4585	openai/o1-pro	256	\N	OpenAI: o1-pro	\N	0	2026-06-19 03:54:01.067753+05:30	\N	\N
4757	354	4585	mistralai/mistral-small-3.1-24b-instruct	257	\N	Mistral: Mistral Small 3.1 24B	\N	0	2026-06-19 03:54:01.080123+05:30	\N	\N
4758	354	4585	google/gemma-3-4b-it	258	\N	Google: Gemma 3 4B	\N	0	2026-06-19 03:54:01.084292+05:30	\N	\N
4759	354	4585	google/gemma-3-12b-it	259	\N	Google: Gemma 3 12B	\N	0	2026-06-19 03:54:01.086948+05:30	\N	\N
4760	354	4585	cohere/command-a	260	\N	Cohere: Command A	\N	0	2026-06-19 03:54:01.091531+05:30	\N	\N
4761	354	4585	openai/gpt-4o-mini-search-preview	261	\N	OpenAI: GPT-4o-mini Search Preview	\N	0	2026-06-19 03:54:01.098143+05:30	\N	\N
4762	354	4585	openai/gpt-4o-search-preview	262	\N	OpenAI: GPT-4o Search Preview	\N	0	2026-06-19 03:54:01.108159+05:30	\N	\N
4763	354	4585	google/gemma-3-27b-it	264	\N	Google: Gemma 3 27B	\N	0	2026-06-19 03:54:01.137602+05:30	\N	\N
4764	354	4585	mistralai/mistral-saba	269	\N	Mistral: Saba	\N	0	2026-06-19 03:54:01.147636+05:30	\N	\N
4765	354	4585	openai/o3-mini-high	270	\N	OpenAI: o3 Mini High	\N	0	2026-06-19 03:54:01.150739+05:30	\N	\N
4766	354	4585	qwen/qwen2.5-vl-72b-instruct	274	\N	Qwen: Qwen2.5 VL 72B Instruct	\N	0	2026-06-19 03:54:01.168038+05:30	\N	\N
4767	354	4585	qwen/qwen-plus	275	\N	Qwen: Qwen-Plus	\N	0	2026-06-19 03:54:01.173658+05:30	\N	\N
4768	354	4585	openai/o3-mini	276	\N	OpenAI: o3 Mini	\N	0	2026-06-19 03:54:01.180308+05:30	\N	\N
4769	354	4585	mistralai/mistral-small-24b-instruct-2501	277	\N	Mistral: Mistral Small 3	\N	0	2026-06-19 03:54:01.184376+05:30	\N	\N
4770	354	4585	deepseek/deepseek-r1-distill-llama-70b	279	\N	DeepSeek: R1 Distill Llama 70B	\N	0	2026-06-19 03:54:01.186882+05:30	\N	\N
4771	354	4585	deepseek/deepseek-r1	280	\N	DeepSeek: R1	\N	0	2026-06-19 03:54:01.19146+05:30	\N	\N
4772	354	4585	minimax/minimax-01	281	\N	MiniMax: MiniMax-01	\N	0	2026-06-19 03:54:01.193016+05:30	\N	\N
4773	354	4585	deepseek/deepseek-chat	284	\N	DeepSeek: DeepSeek V3	\N	0	2026-06-19 03:54:01.195512+05:30	\N	\N
4774	354	4585	openai/o1	286	\N	OpenAI: o1	\N	0	2026-06-19 03:54:01.198108+05:30	\N	\N
4775	354	4585	cohere/command-r7b-12-2024	287	\N	Cohere: Command R7B (12-2024)	\N	0	2026-06-19 03:54:01.199739+05:30	\N	\N
4776	354	4585	meta-llama/llama-3.3-70b-instruct:free	288	\N	Meta: Llama 3.3 70B Instruct (free)	\N	0	2026-06-19 03:54:01.201698+05:30	\N	\N
4777	354	4585	meta-llama/llama-3.3-70b-instruct	289	\N	Meta: Llama 3.3 70B Instruct	\N	0	2026-06-19 03:54:01.203594+05:30	\N	\N
4778	354	4585	amazon/nova-lite-v1	290	\N	Amazon: Nova Lite 1.0	\N	0	2026-06-19 03:54:01.2054+05:30	\N	\N
4779	354	4585	amazon/nova-micro-v1	291	\N	Amazon: Nova Micro 1.0	\N	0	2026-06-19 03:54:01.207554+05:30	\N	\N
4780	354	4585	amazon/nova-pro-v1	292	\N	Amazon: Nova Pro 1.0	\N	0	2026-06-19 03:54:01.209512+05:30	\N	\N
4781	354	4585	openai/gpt-4o-2024-11-20	293	\N	OpenAI: GPT-4o (2024-11-20)	\N	0	2026-06-19 03:54:01.211148+05:30	\N	\N
4782	354	4585	mistralai/mistral-large-2407	294	\N	Mistral Large 2407	\N	0	2026-06-19 03:54:01.221028+05:30	\N	\N
4783	354	4585	qwen/qwen-2.5-coder-32b-instruct	295	\N	Qwen2.5 Coder 32B Instruct	\N	0	2026-06-19 03:54:01.225427+05:30	\N	\N
4784	354	4585	anthropic/claude-3.5-haiku	297	\N	Anthropic: Claude 3.5 Haiku	\N	0	2026-06-19 03:54:01.230377+05:30	\N	\N
4785	354	4585	qwen/qwen-2.5-7b-instruct	299	\N	Qwen: Qwen2.5 7B Instruct	\N	0	2026-06-19 03:54:01.236441+05:30	\N	\N
4786	354	4585	meta-llama/llama-3.2-3b-instruct:free	303	\N	Meta: Llama 3.2 3B Instruct (free)	\N	0	2026-06-19 03:54:01.241299+05:30	\N	\N
4787	354	4585	meta-llama/llama-3.2-3b-instruct	304	\N	Meta: Llama 3.2 3B Instruct	\N	0	2026-06-19 03:54:01.249519+05:30	\N	\N
4788	354	4585	meta-llama/llama-3.2-1b-instruct	305	\N	Meta: Llama 3.2 1B Instruct	\N	0	2026-06-19 03:54:01.250859+05:30	\N	\N
4789	354	4585	meta-llama/llama-3.2-11b-vision-instruct	306	\N	Meta: Llama 3.2 11B Vision Instruct	\N	0	2026-06-19 03:54:01.258349+05:30	\N	\N
4790	354	4585	qwen/qwen-2.5-72b-instruct	307	\N	Qwen2.5 72B Instruct	\N	0	2026-06-19 03:54:01.26271+05:30	\N	\N
4791	354	4585	cohere/command-r-plus-08-2024	308	\N	Cohere: Command R+ (08-2024)	\N	0	2026-06-19 03:54:01.268882+05:30	\N	\N
4792	354	4585	cohere/command-r-08-2024	309	\N	Cohere: Command R (08-2024)	\N	0	2026-06-19 03:54:01.276953+05:30	\N	\N
4793	354	4585	openai/gpt-4o-2024-08-06	315	\N	OpenAI: GPT-4o (2024-08-06)	\N	0	2026-06-19 03:54:01.286551+05:30	\N	\N
4794	354	4585	meta-llama/llama-3.1-8b-instruct	316	\N	Meta: Llama 3.1 8B Instruct	\N	0	2026-06-19 03:54:01.291722+05:30	\N	\N
4795	354	4585	meta-llama/llama-3.1-70b-instruct	317	\N	Meta: Llama 3.1 70B Instruct	\N	0	2026-06-19 03:54:01.2943+05:30	\N	\N
4796	354	4585	mistralai/mistral-nemo	318	\N	Mistral: Mistral Nemo	\N	0	2026-06-19 03:54:01.297163+05:30	\N	\N
4797	354	4585	openai/gpt-4o-mini-2024-07-18	319	\N	OpenAI: GPT-4o-mini (2024-07-18)	\N	0	2026-06-19 03:54:01.299942+05:30	\N	\N
4798	354	4585	openai/gpt-4o-mini	320	\N	OpenAI: GPT-4o-mini	\N	0	2026-06-19 03:54:01.304432+05:30	\N	\N
4799	354	4585	google/gemma-2-27b-it	321	\N	Google: Gemma 2 27B	\N	0	2026-06-19 03:54:01.308295+05:30	\N	\N
4800	354	4585	openai/gpt-4o-2024-05-13	322	\N	OpenAI: GPT-4o (2024-05-13)	\N	0	2026-06-19 03:54:01.311758+05:30	\N	\N
4801	354	4585	openai/gpt-4o	323	\N	OpenAI: GPT-4o	\N	0	2026-06-19 03:54:01.316375+05:30	\N	\N
4802	354	4585	meta-llama/llama-3-8b-instruct	324	\N	Meta: Llama 3 8B Instruct	\N	0	2026-06-19 03:54:01.321334+05:30	\N	\N
4803	354	4585	meta-llama/llama-3-70b-instruct	325	\N	Meta: Llama 3 70B Instruct	\N	0	2026-06-19 03:54:01.329144+05:30	\N	\N
4804	354	4585	mistralai/mixtral-8x22b-instruct	326	\N	Mistral: Mixtral 8x22B Instruct	\N	0	2026-06-19 03:54:01.333328+05:30	\N	\N
4805	354	4585	openai/gpt-4-turbo	328	\N	OpenAI: GPT-4 Turbo	\N	0	2026-06-19 03:54:01.337972+05:30	\N	\N
4806	354	4585	anthropic/claude-3-haiku	329	\N	Anthropic: Claude 3 Haiku	\N	0	2026-06-19 03:54:01.346799+05:30	\N	\N
4807	354	4585	mistralai/mistral-large	330	\N	Mistral Large	\N	0	2026-06-19 03:54:01.3532+05:30	\N	\N
4808	354	4585	openai/gpt-4-turbo-preview	331	\N	OpenAI: GPT-4 Turbo Preview	\N	0	2026-06-19 03:54:01.362104+05:30	\N	\N
4809	354	4585	openai/gpt-3.5-turbo-0613	332	\N	OpenAI: GPT-3.5 Turbo (older v0613)	\N	0	2026-06-19 03:54:01.364347+05:30	\N	\N
4810	354	4585	openai/gpt-3.5-turbo-instruct	334	\N	OpenAI: GPT-3.5 Turbo Instruct	\N	0	2026-06-19 03:54:01.383472+05:30	\N	\N
4811	354	4585	openai/gpt-3.5-turbo-16k	335	\N	OpenAI: GPT-3.5 Turbo 16k	\N	0	2026-06-19 03:54:01.38627+05:30	\N	\N
4812	354	4585	openai/gpt-4	339	\N	OpenAI: GPT-4	\N	0	2026-06-19 03:54:01.391066+05:30	\N	\N
4813	354	4585	openai/gpt-3.5-turbo	340	\N	OpenAI: GPT-3.5 Turbo	\N	0	2026-06-19 03:54:01.393703+05:30	\N	\N
\.


--
-- Data for Name: credential_providers; Type: TABLE DATA; Schema: ag_system; Owner: -
--

COPY ag_system.credential_providers (provider_key, display_name, category, config_schema, icon_url, docs_url, supports_user, supports_verify, is_active, sort_order, created_at, org_app) FROM stdin;
jira	Jira Cloud	integration	{"fields": [{"key": "server_url", "help": "Your Atlassian Cloud or Server instance URL", "type": "url", "label": "Jira Server URL", "required": true, "is_secret": false, "placeholder": "https://your-domain.atlassian.net"}, {"key": "email", "help": "Email associated with your Atlassian account", "type": "email", "label": "Jira Account Email", "required": true, "is_secret": false, "placeholder": "you@company.com"}, {"key": "api_token", "help": "Generate at https://id.atlassian.com/manage-profile/security/api-tokens", "type": "password", "label": "API Token", "required": true, "is_secret": true, "placeholder": "Enter your Jira API token"}]}	\N	\N	t	t	t	20	2026-06-04 11:15:35.843508+05:30	f
m365	Microsoft 365 (Outlook)	integration	{"fields": [{"key": "tenant_id", "help": "Azure Portal > Microsoft Entra ID > Overview. Set once by an admin.", "type": "text", "label": "Azure AD Tenant ID", "scope": "org", "required": true, "is_secret": false, "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}, {"key": "client_id", "help": "App Registration > Overview > Application (client) ID. Set once by an admin.", "type": "text", "label": "Application (Client) ID", "scope": "org", "required": true, "is_secret": false, "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}, {"key": "client_secret", "help": "App Registration > Certificates & Secrets > Client secrets > Value. Set once by an admin.", "type": "password", "label": "Client Secret Value", "scope": "org", "required": true, "is_secret": true, "placeholder": "Enter the client secret value (not the ID)"}, {"key": "user_email", "help": "The Microsoft 365 mailbox you want the agent to access — usually your own work email.", "type": "email", "label": "Your Mailbox Email", "scope": "user", "required": true, "is_secret": false, "placeholder": "you@company.com"}]}	\N	\N	t	t	t	21	2026-06-04 11:15:35.843508+05:30	t
smtp	SMTP Email	integration	{"fields": [{"key": "server", "help": "SMTP server hostname", "type": "text", "label": "SMTP Server", "required": true, "is_secret": false, "placeholder": "smtp.gmail.com"}, {"key": "port", "help": "Usually 587 (TLS) or 465 (SSL)", "type": "number", "label": "Port", "required": true, "is_secret": false, "placeholder": "587"}, {"key": "username", "help": "SMTP authentication username", "type": "text", "label": "Username / Email", "required": true, "is_secret": false, "placeholder": "you@gmail.com"}, {"key": "use_tls", "type": "boolean", "label": "Use TLS", "default": true, "required": false, "is_secret": false}, {"key": "password", "help": "For Gmail, use App Password from myaccount.google.com > Security > App passwords", "type": "password", "label": "Password / App Password", "required": true, "is_secret": true, "placeholder": "Enter SMTP password"}]}	\N	\N	t	t	t	22	2026-06-04 11:15:35.843508+05:30	f
imap	IMAP Email	integration	{"fields": [{"key": "server", "help": "IMAP server hostname", "type": "text", "label": "IMAP Server", "required": true, "is_secret": false, "placeholder": "imap.gmail.com"}, {"key": "port", "help": "Usually 993 (SSL) or 143 (STARTTLS)", "type": "number", "label": "Port", "required": false, "is_secret": false, "placeholder": "993"}, {"key": "username", "type": "text", "label": "Username / Email", "required": true, "is_secret": false, "placeholder": "you@gmail.com"}, {"key": "use_ssl", "type": "boolean", "label": "Use SSL", "default": true, "required": false, "is_secret": false}, {"key": "password", "help": "For Gmail, use App Password", "type": "password", "label": "Password / App Password", "required": true, "is_secret": true, "placeholder": "Enter IMAP password"}]}	\N	\N	t	t	t	23	2026-06-04 11:15:35.843508+05:30	f
confluence	Confluence	integration	{"fields": [{"key": "url", "help": "Your Confluence Cloud or Server base URL", "type": "url", "label": "Confluence Base URL", "required": true, "is_secret": false, "placeholder": "https://your-domain.atlassian.net/wiki"}, {"key": "email", "type": "email", "label": "Account Email", "required": true, "is_secret": false, "placeholder": "you@company.com"}, {"key": "api_token", "help": "Same as Jira API token from Atlassian account settings", "type": "password", "label": "API Token", "required": true, "is_secret": true, "placeholder": "Enter your Confluence API token"}]}	\N	\N	t	t	t	24	2026-06-04 11:15:35.843508+05:30	f
slack	Slack	integration	{"fields": [{"key": "bot_token", "help": "From Slack App > OAuth & Permissions > Bot User OAuth Token", "type": "password", "label": "Bot OAuth Token", "required": true, "is_secret": true, "placeholder": "xoxb-xxxx-xxxx-xxxx"}]}	\N	\N	f	t	t	25	2026-06-04 11:15:35.843508+05:30	f
telegram	Telegram Bot	platform	{"fields": [{"key": "allowed_users", "help": "Comma-separated Telegram user IDs that can interact with the bot", "type": "text", "label": "Allowed User IDs", "required": false, "is_secret": false, "placeholder": "123456789,987654321"}, {"key": "home_channel", "type": "text", "label": "Home Channel ID", "required": false, "is_secret": false, "placeholder": "-1001234567890"}, {"key": "bot_token", "help": "Get from @BotFather on Telegram", "type": "password", "label": "Bot Token", "required": true, "is_secret": true, "placeholder": "123456:ABC-DEF..."}]}	\N	\N	f	f	t	60	2026-06-04 11:15:35.843508+05:30	f
\.


--
-- Name: roles_role_id_seq; Type: SEQUENCE SET; Schema: ag_auth; Owner: -
--

SELECT pg_catalog.setval('ag_auth.roles_role_id_seq', 5, true);


--
-- Name: agent_personas_persona_id_seq; Type: SEQUENCE SET; Schema: ag_system; Owner: -
--

SELECT pg_catalog.setval('ag_system.agent_personas_persona_id_seq', 5, true);


--
-- Name: applications_app_id_seq; Type: SEQUENCE SET; Schema: ag_system; Owner: -
--

SELECT pg_catalog.setval('ag_system.applications_app_id_seq', 5, true);


--
-- Name: code_types_code_type_id_seq; Type: SEQUENCE SET; Schema: ag_system; Owner: -
--

SELECT pg_catalog.setval('ag_system.code_types_code_type_id_seq', 355, true);


--
-- Name: codes_code_id_seq; Type: SEQUENCE SET; Schema: ag_system; Owner: -
--

SELECT pg_catalog.setval('ag_system.codes_code_id_seq', 4813, true);


--
-- Name: modules_module_id_seq; Type: SEQUENCE SET; Schema: ag_system; Owner: -
--

SELECT pg_catalog.setval('ag_system.modules_module_id_seq', 12, true);


--
-- PostgreSQL database dump complete
--

\unrestrict QBIE3dsSrDyGPdIeGnkxhFYZ0CEEWrEVTNLP1LUeeVDePv7Uvq6leqipVVkNSIV


-- ag_system.configs — non-secret, non-env-endpoint defaults only
COPY ag_system.configs (config_id,config_key,config_value,description,is_secret,is_active,created_at,updated_at,config_type,config_group,sort_order,requires_restart) FROM stdin;
133	agent.approval_mode	irreversible	When to require human approval (none/irreversible/all)	f	t	2026-06-13 00:37:37.160471+05:30	2026-06-13 00:39:22.818391+05:30	select	agent	26	f
109	agent.compaction_llm	true	LLM compaction tier (E.1) — degrades to heuristic on failure	f	t	2026-06-12 23:33:16.921828+05:30	2026-06-13 00:37:37.160471+05:30	boolean	agent	22	f
110	agent.conversation_token_budget	2000000	Soft per-conversation token cap — stops runaway loops	f	t	2026-06-12 23:33:16.921828+05:30	2026-06-13 00:37:37.160471+05:30	number	agent	21	f
151	agent.data_dir	.ag_data	Path to the agent data directory	f	t	2026-06-13 00:44:20.717132+05:30	2026-06-13 00:44:20.717132+05:30	text	agent	27	f
24	agent.dynamic_integrations	true	Enable dynamic spec-derived API integration tools (ag_api)	f	t	2026-06-26 12:16:00.026843+05:30	2026-06-26 12:16:00.026843+05:30	bool	agent	100	f
157	agent.dynamic_tools	true	Send only turn-relevant tools (token reduction)	f	t	2026-06-13 14:47:43.410117+05:30	2026-06-13 14:47:43.410117+05:30	text		100	f
107	agent.history_token_budget	64000	Explicit history budget (cost lever) — wins over window derivation; was implicit 32k	f	t	2026-06-12 23:33:16.921828+05:30	2026-06-13 00:44:20.717132+05:30	number	agent	3	f
127	agent.max_concurrent_turns	8	Max concurrent agent turns per process	f	t	2026-06-13 00:37:37.160471+05:30	2026-06-13 00:37:37.160471+05:30	number	agent	20	f
10	agent.max_tools	20	Max tools per agent definition	f	t	2026-05-30 08:59:12.237631+05:30	2026-06-13 00:37:37.160471+05:30	number	agent	1	f
112	agent.memory_llm_salience	true	Distill auto-memories into clean facts via cheap-model call (B.3); degrades to raw form	f	t	2026-06-12 23:46:34.082795+05:30	2026-06-13 00:37:37.160471+05:30	boolean	agent	23	f
131	agent.planning_enabled	true	Enable explicit planning for complex tasks	f	t	2026-06-13 00:37:37.160471+05:30	2026-06-13 00:37:37.160471+05:30	boolean	agent	24	f
11	agent.timeout_seconds	300	Default agent run timeout	f	t	2026-05-30 08:59:12.237631+05:30	2026-06-13 00:37:37.160471+05:30	number	agent	2	f
111	agent.tool_result_guard	true	Input-side injection guard: frame instruction-like tool output as untrusted data (I.3)	f	t	2026-06-12 23:46:34.082795+05:30	2026-06-13 00:37:37.160471+05:30	boolean	agent	25	f
6	brain.auto_sync	true	Enable automatic data sync	f	t	2026-05-30 08:59:12.237631+05:30	2026-06-13 00:37:37.160471+05:30	boolean	brain	1	f
156	brain.chunk_overlap	320	Chunk overlap in chars	f	t	2026-06-13 14:24:20.171241+05:30	2026-06-13 14:24:20.171241+05:30	text		100	f
155	brain.chunk_size	2000	Child chunk size in chars (~500 tokens)	f	t	2026-06-13 14:24:20.171241+05:30	2026-06-13 14:24:20.171241+05:30	text		100	f
154	brain.chunking_enabled	true	Parent-child chunk embeddings for precise dense retrieval (V020)	f	t	2026-06-13 14:24:20.171241+05:30	2026-06-13 14:24:20.171241+05:30	text		100	f
7	brain.sync_interval	30m	Sync interval (e.g. 30m, 1h)	f	t	2026-05-30 08:59:12.237631+05:30	2026-06-13 00:37:37.160471+05:30	text	brain	2	f
106	llm.context_window	1048576	deepseek-v4-flash context length (OpenRouter); used by per-model budget derivation	f	t	2026-06-12 23:33:16.921828+05:30	2026-06-13 00:37:37.160471+05:30	number	llm	12	f
126	llm.debug_dump_payload	false	Write raw LLM payloads to temp/ for debug	f	t	2026-06-13 00:37:37.160471+05:30	2026-06-13 15:03:36.685938+05:30	boolean	llm	18	f
116	llm.embedding_dimensions	768	Must match ag_brain.documents.embedding vector(768) (V018)	f	t	2026-06-12 23:58:40.274315+05:30	2026-06-13 00:37:37.160471+05:30	number	llm	16	f
113	llm.embedding_model	nomic-embed-text	Local Ollama embedding model (768-dim) — activates vector RAG	f	t	2026-06-12 23:58:40.274315+05:30	2026-06-13 00:37:37.160471+05:30	text	llm	13	f
108	llm.fallback_model	deepseek-v4-pro	Cross-vendor fallback when primary exhausts retries (128k ctx, cheap)	f	t	2026-06-12 23:33:16.921828+05:30	2026-06-20 15:56:05.424594+05:30	text	llm	10	f
4	llm.max_tokens	16000	Max output tokens per request	f	t	2026-05-30 08:59:12.237631+05:30	2026-06-20 22:07:55.559489+05:30	number	llm	4	f
2	llm.model	deepseek-v4-flash	Default LLM model	f	t	2026-05-30 08:59:12.237631+05:30	2026-06-20 22:07:55.53719+05:30	text	llm	2	f
125	llm.prompt_caching	true	Enable Anthropic prompt caching	f	t	2026-06-13 00:37:37.160471+05:30	2026-06-13 00:37:37.160471+05:30	boolean	llm	17	f
1	llm.provider	deepseek	LLM API provider	f	t	2026-05-30 08:59:12.237631+05:30	2026-06-20 22:07:55.528113+05:30	text	llm	1	f
43	llm.provider_order	DeepInfra	\N	f	t	2026-06-08 15:57:50.158441+05:30	2026-06-20 22:07:55.550256+05:30	text	llm	7	f
119	llm.small_model		Cheap model for classification, routing, compaction	f	t	2026-06-13 00:37:37.160471+05:30	2026-06-13 00:37:37.160471+05:30	text	llm	11	f
5	llm.temperature	0.5	Default temperature	f	t	2026-05-30 08:59:12.237631+05:30	2026-06-20 22:07:55.564243+05:30	text	llm	5	f
9	memory.decay_days	7	Days before session memories decay	f	t	2026-05-30 08:59:12.237631+05:30	2026-06-13 00:37:37.160471+05:30	number	memory	2	f
8	memory.session_limit	50	Max memories per session layer	f	t	2026-05-30 08:59:12.237631+05:30	2026-06-13 00:37:37.160471+05:30	number	memory	1	f
\.

