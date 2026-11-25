-- Core labels each rating, and again each shared conversation (modules/labeling/), with one
-- value per group of config.yaml labeling.groups, so a row's labels are one JSON object:
-- {"<group>": "<value>", ...}, with only the groups the model could tell ({} for none).
-- The three fixed label columns move into the object, each value renamed to its word in
-- config.yaml (go -> Go, fix -> Bug fix, ...); a value not listed here keeps its word.
ALTER TABLE feedback   ADD COLUMN labels JSONB NOT NULL DEFAULT '{}';
ALTER TABLE transcript ADD COLUMN labels JSONB NOT NULL DEFAULT '{}';
CREATE TEMP TABLE renamed_label (label_group TEXT, old_value TEXT, new_value TEXT);
INSERT INTO renamed_label (label_group, old_value, new_value) VALUES
    ('business_case', 'devops', 'DevOps'), ('business_case', 'mlops', 'MLOps'),
    ('business_case', 'ml', 'ML'), ('business_case', 'imaging', 'Imaging'),
    ('business_case', 'data', 'Data'), ('business_case', 'frontend', 'Frontend'),
    ('business_case', 'backend', 'Backend'), ('business_case', 'mobile', 'Mobile'),
    ('business_case', 'security', 'Security'), ('business_case', 'scripting', 'Scripting'),
    ('business_case', 'writing', 'Writing'), ('business_case', 'other', 'Other'),
    ('language', 'go', 'Go'), ('language', 'python', 'Python'),
    ('language', 'typescript', 'TypeScript'), ('language', 'javascript', 'JavaScript'),
    ('language', 'java', 'Java'), ('language', 'csharp', 'C#'), ('language', 'cpp', 'C++'),
    ('language', 'rust', 'Rust'), ('language', 'bash', 'Bash'), ('language', 'sql', 'SQL'),
    ('language', 'terraform', 'Terraform'), ('language', 'none', 'No code'),
    ('language', 'other', 'Other'),
    ('task_type', 'feat', 'New feature'), ('task_type', 'fix', 'Bug fix'),
    ('task_type', 'docs', 'Docs'), ('task_type', 'style', 'Style'),
    ('task_type', 'refactor', 'Refactor'), ('task_type', 'test', 'Tests'),
    ('task_type', 'chore', 'Chore'), ('task_type', 'other', 'Other');
UPDATE transcript SET labels = jsonb_strip_nulls(jsonb_build_object(
    'business_case', COALESCE((SELECT new_value FROM renamed_label
        WHERE label_group = 'business_case' AND old_value = business_case), business_case),
    'language', COALESCE((SELECT new_value FROM renamed_label
        WHERE label_group = 'language' AND old_value = language), language),
    'task_type', COALESCE((SELECT new_value FROM renamed_label
        WHERE label_group = 'task_type' AND old_value = task_type), task_type)));
DROP TABLE renamed_label;

DROP VIEW feedback_with_labels;
ALTER TABLE transcript DROP COLUMN business_case, DROP COLUMN language, DROP COLUMN task_type;

-- Each rating with its labels: the rating's own, and over them, group by group, those of
-- its conversation - the transcript posted under the same request_id, of which there is
-- at most one - since the model read the comment and the conversation for those. So the
-- dashboard's label filters narrow the rating panels too.
CREATE VIEW feedback_with_labels AS
SELECT f.id, f.created_at, f.session_id, f.skill_name, f.agent, f.eval_name, f.score,
       f.comment, f.request_id, f.labels || COALESCE(t.labels, '{}') AS labels
FROM feedback f
LEFT JOIN transcript t ON t.request_id = f.request_id;
