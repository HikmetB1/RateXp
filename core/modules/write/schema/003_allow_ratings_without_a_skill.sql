-- A whole-session rating is not about any one skill, so skill_name stops being
-- required. Ratings posted by a skill hook still carry it; session ratings leave
-- it null, which the dashboard shows as an empty Skill cell.
ALTER TABLE feedback   ALTER COLUMN skill_name DROP NOT NULL;
ALTER TABLE transcript ALTER COLUMN skill_name DROP NOT NULL;
