-- Removes the sample apps the bootstrap snapshot carries for other products
-- (an "SMSystem" support bot and a "Fleet" support bot with its "Fleet API"
-- integration). They mean nothing on a Storeglance install and show up in the
-- admin UI. Safe to re-run. Anything already in use is deactivated, not deleted.
DO $$
DECLARE a record;
BEGIN
  FOR a IN SELECT app_id, name FROM ag_system.applications
            WHERE name IN ('SMSystem Support', 'Fleet Support') LOOP
    BEGIN
      DELETE FROM ag_system.applications WHERE app_id = a.app_id;  -- personas cascade
      RAISE NOTICE 'removed demo app %', a.name;
    EXCEPTION WHEN foreign_key_violation THEN
      UPDATE ag_system.applications SET is_active = false, updated_at = now() WHERE app_id = a.app_id;
      UPDATE ag_system.agent_personas SET is_active = false, updated_at = now() WHERE app_id = a.app_id;
      RAISE NOTICE 'demo app % is referenced; deactivated', a.name;
    END;
  END LOOP;
  BEGIN
    DELETE FROM ag_cred.providers WHERE provider_key = 'api_fleet';
  EXCEPTION WHEN foreign_key_violation THEN
    UPDATE ag_cred.providers SET is_active = false WHERE provider_key = 'api_fleet';
  END;
END $$;
