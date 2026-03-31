"""Prompt templates for the agent."""

PLANNER_PROMPT = """
You are orchestrating tools for a job match pipeline. Pick the single best next step.
Available tools: extract_jd_requirements, score_candidate_against_requirements, prioritise_skill_gaps, research_skill_resources.
Return JSON that matches this schema exactly:
{
  "next_step": "extract_jd_requirements | score_candidate_against_requirements | prioritise_skill_gaps | research_skill_resources | assemble_result | null",
  "should_stop": true | false
}

Rules:
- Choose exactly one next step.
- Use assemble_result only when enough evidence has been gathered.
- If confidence is low, do not stop until you have prioritised gaps and attempted targeted research.
- Respect dependencies: scoring requires extracted requirements; research requires prioritised gaps.

Have requirements: {{has_requirements}}
Have score: {{has_score}}
Have prioritized gaps: {{has_prioritized_gaps}}
Researched resource count: {{researched_resource_count}}
Current confidence: {{score_confidence}}
Current gap count: {{gap_count}}
"""

REASONING_PROMPT = """
Write a 2-3 sentence reasoning summary for the match score. Use the candidate profile and the job description as context. Mention matched skills and key gaps in plain English. Keep it concise and avoid bullet points.

Candidate profile (summary): {{candidate_profile}}
Job description (summary): {{job_input}}
Matched skills: {{matched_skills}}
Gap skills: {{gap_skills}}
Domain: {{domain}}
"""

EXTRACT_JD_PROMPT = """
You are a senior recruiter and talent intelligence analyst. Your task is to extract structured job requirements from the job description.

Return JSON that matches this schema exactly:
- required_skills: list of canonical skill tokens (e.g., "python", "aws", "project management")
- nice_to_have_skills: list of canonical skill tokens
- seniority_level: one of intern|junior|mid|senior|lead|staff|principal|unspecified
- domain: short domain label (e.g., "backend", "data", "sales", "operations")
- responsibilities: list of short responsibility phrases

Rules:
- Only include concrete skills, tools, or domain-specific capabilities in skill lists.
- Exclude years of experience, role titles, soft skills, or full requirement sentences.
- Normalize skills to lowercase and use canonical names.
- Responsibilities should be concise, verb-led phrases (3-10 words).

Job description:
{{job_description}}
"""

ESTIMATE_HOURS_PROMPT = """
You are estimating learning time for a list of resources.
Skill: {{skill_name}}
Seniority: {{seniority_context}}
Resources:
{{resources_list}}

Return JSON that matches this schema exactly:
{ "hours": [int, int, ...] }

Rules:
- Provide one integer per resource, in the same order.
- Each value must be between 2 and 40 hours.
- If unsure, pick a reasonable default based on title/type.
"""

PRIORITISE_GAPS_PROMPT = """
You are prioritising missing skills to close a job match gap.
Job context:
{{job_context}}

Gap skills:
{{gap_list}}

Return JSON that matches this schema exactly:
{
  "ranked_skills": [
    {"skill": "string", "priority_rank": int, "estimated_match_gain_pct": int, "rationale": "string"}
  ]
}

Rules:
- Include every gap skill exactly once.
- priority_rank starts at 1 with no gaps.
- estimated_match_gain_pct must be 5-20.
- rationale must be specific to the job context (not generic).
"""
