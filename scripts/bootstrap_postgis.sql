-- WohnWerk requires PostGIS in the existing PostgreSQL database.
--
-- IMPORTANT: this SQL only enables the extension. The PostgreSQL container/image
-- itself must first contain a PostGIS package compatible with the running PostgreSQL
-- major version.

CREATE EXTENSION IF NOT EXISTS postgis;

SELECT
    PostGIS_Version() AS postgis_version,
    current_database() AS database_name;
