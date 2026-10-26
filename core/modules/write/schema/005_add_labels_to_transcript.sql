-- Core labels each consented trajectory (modules/labeling/): one word each for its
-- business case, main language and task type, from config.yaml labeling.labels. NULL
-- when it was not labeled: labeling off or failed, or an oversized stub.
ALTER TABLE transcript
    ADD COLUMN business_case TEXT,
    ADD COLUMN language      TEXT,
    ADD COLUMN task_type     TEXT;

-- Each rating with the labels of its conversation - the transcript posted under the
-- same request_id, of which there is at most one - so the dashboard's label filters
-- narrow the rating panels too. A rating whose conversation was not stored gets NULLs.
CREATE VIEW feedback_with_labels AS
SELECT f.id, f.created_at, f.session_id, f.skill_name, f.agent, f.eval_name, f.score,
       f.comment, f.request_id, t.business_case, t.language, t.task_type
FROM feedback f
LEFT JOIN transcript t ON t.request_id = f.request_id;
