from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote_plus

import requests

from pelgo.domain.model.shared_types import ConfidenceLevel
from pelgo.domain.model.tool_schema import (
    ExtractJDRequirementsInput,
    ExtractJDRequirementsOutput,
    PrioritiseSkillGapsInput,
    PrioritiseSkillGapsOutput,
    PrioritisedSkillGap,
    ResearchSkillResourcesInput,
    ResearchSkillResourcesOutput,
    ResourceType,
    ScoreCandidateInput,
    ScoreCandidateOutput,
    ScoreCandidateDimensionScores,
    SkillResource,
)

DEFAULT_TIMEOUT_SECONDS = 10
MAX_RESOURCES = 3


def _is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def _fetch_url(url: str, timeout_seconds: int) -> str:
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return response.text


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_+.#-]{1,}", text.lower())
    stop = {
        "and",
        "the",
        "with",
        "for",
        "you",
        "your",
        "will",
        "role",
        "job",
        "our",
        "are",
        "we",
        "a",
        "an",
        "to",
        "in",
        "of",
        "on",
        "as",
    }
    return [t for t in tokens if t not in stop]


def _extract_seniority(text: str) -> str:
    for level in ["intern", "junior", "mid", "senior", "lead", "staff", "principal"]:
        if re.search(rf"\b{level}\b", text, re.IGNORECASE):
            return level
    return "unspecified"


def _extract_responsibilities(text: str) -> list[str]:
    sentences = re.split(r"[\n\.]+", text)
    responsibilities = []
    for sentence in sentences:
        if re.search(r"\b(responsible|you will|duties|will be)\b", sentence, re.I):
            cleaned = sentence.strip()
            if cleaned:
                responsibilities.append(cleaned)
    return responsibilities[:8]


def _extract_skills(text: str, keywords: Iterable[str]) -> list[str]:
    found = []
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", text, re.I):
            found.append(keyword)
    return found


def _extract_skills_from_text(text: str) -> tuple[list[str], list[str]]:
    skill_candidates = sorted(set(_tokenize(text)))
    required_section = []
    nice_section = []
    for line in re.split(r"[\n\.]+", text):
        if re.search(r"\b(required|must have|must)\b", line, re.I):
            required_section.append(line)
        if re.search(r"\b(preferred|nice to have|bonus)\b", line, re.I):
            nice_section.append(line)
    required_text = " ".join(required_section) if required_section else text
    nice_text = " ".join(nice_section)
    required_skills = _extract_skills(required_text, skill_candidates)[:12]
    nice_skills = _extract_skills(nice_text, skill_candidates)[:8]
    return required_skills, nice_skills


@dataclass(frozen=True)
class ExtractJDRequirementsTool:
    name: str = "extract_jd_requirements"
    input_model = ExtractJDRequirementsInput
    output_model = ExtractJDRequirementsOutput
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def __call__(self, payload: ExtractJDRequirementsInput) -> ExtractJDRequirementsOutput:
        text = payload.job_url_or_text
        if _is_url(text):
            text = _fetch_url(text, self.timeout_seconds)
        cleaned = _clean_text(text)
        required_skills, nice_skills = _extract_skills_from_text(cleaned)
        seniority = _extract_seniority(cleaned)
        responsibilities = _extract_responsibilities(cleaned)
        domain = "general"
        domain_candidates = ["data", "backend", "frontend", "machine learning", "ai"]
        for candidate in domain_candidates:
            if candidate in cleaned.lower():
                domain = candidate
                break
        return ExtractJDRequirementsOutput(
            required_skills=required_skills,
            nice_to_have_skills=nice_skills,
            seniority_level=seniority,
            domain=domain,
            responsibilities=responsibilities,
        )


@dataclass(frozen=True)
class ScoreCandidateTool:
    name: str = "score_candidate_against_requirements"
    input_model = ScoreCandidateInput
    output_model = ScoreCandidateOutput

    def __call__(self, payload: ScoreCandidateInput) -> ScoreCandidateOutput:
        candidate_text = payload.candidate_profile
        required_skills = payload.requirements.required_skills
        candidate_skills = set(_tokenize(candidate_text))
        required_set = {s.lower() for s in required_skills}
        matched = sorted(required_set.intersection(candidate_skills))
        gaps = sorted(required_set.difference(candidate_skills))
        coverage = len(matched) / max(1, len(required_set))

        jd_completeness_parts = [
            1 if payload.requirements.required_skills else 0,
            1 if payload.requirements.responsibilities else 0,
            1 if payload.requirements.seniority_level else 0,
            1 if payload.requirements.domain else 0,
        ]
        jd_completeness = sum(jd_completeness_parts) / len(jd_completeness_parts)

        candidate_seniority = _extract_seniority(candidate_text)
        jd_seniority = payload.requirements.seniority_level
        if candidate_seniority == jd_seniority:
            seniority_alignment = 1.0
        elif candidate_seniority == "unspecified" or jd_seniority == "unspecified":
            seniority_alignment = 0.5
        else:
            seniority_alignment = 0.0

        domain_keywords = set(_tokenize(payload.requirements.domain))
        overlap = domain_keywords.intersection(candidate_skills)
        domain_overlap = len(overlap) / max(1, len(domain_keywords))

        confidence_score = (
            0.2 * jd_completeness
            + 0.4 * coverage
            + 0.2 * seniority_alignment
            + 0.2 * domain_overlap
        )

        if confidence_score >= 0.75:
            confidence = ConfidenceLevel.high
        elif confidence_score >= 0.5:
            confidence = ConfidenceLevel.medium
        else:
            confidence = ConfidenceLevel.low

        overall = int(round(confidence_score * 100))
        dimension_scores = ScoreCandidateDimensionScores(
            skills=int(round(coverage * 100)),
            experience=int(round(domain_overlap * 100)),
            seniority_fit=int(round(seniority_alignment * 100)),
        )

        return ScoreCandidateOutput(
            overall_score=overall,
            dimension_scores=dimension_scores,
            matched_skills=matched,
            gap_skills=gaps,
            confidence=confidence,
        )


@dataclass(frozen=True)
class PrioritiseSkillGapsTool:
    name: str = "prioritise_skill_gaps"
    input_model = PrioritiseSkillGapsInput
    output_model = PrioritiseSkillGapsOutput

    def __call__(self, payload: PrioritiseSkillGapsInput) -> PrioritiseSkillGapsOutput:
        context = payload.job_market_context.lower()
        scored = []
        for skill in payload.gap_skills:
            score = 2 if skill.lower() in context else 1
            scored.append((skill, score))
        scored.sort(key=lambda item: (-item[1], item[0]))
        ranked = []
        for index, (skill, score) in enumerate(scored, start=1):
            gain = max(5, 15 - index)
            ranked.append(
                PrioritisedSkillGap(
                    skill=skill,
                    priority_rank=index,
                    estimated_match_gain_pct=gain,
                    rationale=(
                        "Higher impact based on job context" if score > 1 else "Baseline gap"
                    ),
                )
            )
        return PrioritiseSkillGapsOutput(ranked_skills=ranked)


@dataclass(frozen=True)
class ResearchSkillResourcesTool:
    name: str = "research_skill_resources"
    input_model = ResearchSkillResourcesInput
    output_model = ResearchSkillResourcesOutput
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def __call__(self, payload: ResearchSkillResourcesInput) -> ResearchSkillResourcesOutput:
        query_parts = [payload.skill_name, "course"]
        if payload.seniority_context:
            query_parts.append(payload.seniority_context)
        query = quote_plus(" ".join(query_parts))
        url = f"https://duckduckgo.com/html/?q={query}"
        html = _fetch_url(url, self.timeout_seconds)
        links = re.findall(r"result__a[^>]+href=\"(https?://[^\"]+)\"", html)
        titles = re.findall(r"result__a[^>]*>(.*?)</a>", html)
        resources = []
        for title, link in zip(titles, links):
            cleaned_title = re.sub(r"<[^>]+>", "", title).strip()
            if not cleaned_title:
                continue
            resource_type = ResourceType.doc if "docs" in link else ResourceType.course
            resources.append(
                SkillResource(
                    title=cleaned_title,
                    url=link,
                    estimated_hours=8,
                    type=resource_type,
                )
            )
            if len(resources) >= MAX_RESOURCES:
                break
        relevance = 80 if resources else 40
        return ResearchSkillResourcesOutput(resources=resources, relevance_score=relevance)
