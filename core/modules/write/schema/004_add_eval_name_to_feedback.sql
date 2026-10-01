-- Each rating names the eval (survey) it answered; the dashboard shows it in its
-- Eval column. Every rating stored before this answered the one survey there
-- was, human-satisfaction, so those rows are given its name.
ALTER TABLE feedback ADD COLUMN eval_name TEXT;
UPDATE feedback SET eval_name = 'human-satisfaction';
