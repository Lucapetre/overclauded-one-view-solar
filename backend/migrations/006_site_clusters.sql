-- Synthetic site profiles may belong to a named cluster of nearby demo installations
-- (see backend/fixtures/site_profiles.json); standalone sites keep NULL.
ALTER TABLE site_profiles ADD COLUMN cluster TEXT;
