from __future__ import annotations

import os
from typing import Any

import requests
from flask import Flask, jsonify, make_response, render_template, request


BACKEND_API_URL = os.getenv(
    "BACKEND_API_URL", "http://127.0.0.1:5001"
).rstrip("/")
PORT = int(os.getenv("PORT", "8082"))
BACKEND_TIMEOUT = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "10"))
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT_SECONDS", "180"))

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
session = requests.Session()


class BackendUnavailable(Exception):
    """Raised when the Student 2 backend cannot be reached."""


def backend_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> tuple[Any, int]:
    try:
        response = session.request(
            method,
            f"{BACKEND_API_URL}{path}",
            json=json_body,
            params=params,
            timeout=timeout or BACKEND_TIMEOUT,
        )
    except requests.Timeout as error:
        raise BackendUnavailable(
            "The Student 2 backend request timed out."
        ) from error
    except requests.RequestException as error:
        raise BackendUnavailable(
            "The Student 2 backend is unavailable."
        ) from error

    try:
        payload = response.json()
    except ValueError:
        payload = {
            "error": "The Student 2 backend returned invalid data."
        }

    return payload, response.status_code


def error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        message = payload.get("error") or payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return fallback


def positive_integer(raw_value: str | None, field_name: str) -> int:
    try:
        value = int(raw_value or "")
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a positive integer.") from error

    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def non_negative_number(raw_value: str | None, field_name: str) -> float:
    try:
        value = float(raw_value or "0")
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a number.") from error

    if value < 0:
        raise ValueError(f"{field_name} must not be negative.")
    return value


def response_with_trigger(
    html: str,
    trigger_name: str | None = None,
):
    response = make_response(html, 200)
    if trigger_name:
        response.headers["HX-Trigger"] = trigger_name
    return response


def fetch_collection(
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    payload, status = backend_request("GET", path, params=params)
    if status != 200:
        raise BackendUnavailable(
            error_message(payload, "Unable to load data from the backend.")
        )
    if not isinstance(payload, list):
        raise BackendUnavailable("The backend returned an invalid collection.")
    return payload


def fetch_item(path: str) -> tuple[dict[str, Any] | None, str | None]:
    payload, status = backend_request("GET", path)
    if status == 200 and isinstance(payload, dict):
        return payload, None
    return None, error_message(payload, "Unable to load the selected record.")


def render_profiles_section(
    notice: str | None = None,
    notice_tone: str = "success",
) -> str:
    try:
        profiles = fetch_collection("/api/v1/profiles")
        return render_template(
            "partials/profiles_section.html",
            profiles=profiles,
            notice=notice,
            notice_tone=notice_tone,
        )
    except BackendUnavailable as error:
        return render_template(
            "partials/section_error.html",
            section_title="Candidate Profiles",
            message=str(error),
            retry_url="/ui/profiles",
            retry_target="#profiles-section",
        )


def render_resumes_section(
    notice: str | None = None,
    notice_tone: str = "success",
) -> str:
    try:
        profiles = fetch_collection("/api/v1/profiles")
        resumes = fetch_collection("/api/v1/resumes")
        profile_map = {
            profile["id"]: profile.get("full_name", f"Profile {profile['id']}")
            for profile in profiles
        }
        return render_template(
            "partials/resumes_section.html",
            profiles=profiles,
            resumes=resumes,
            profile_map=profile_map,
            notice=notice,
            notice_tone=notice_tone,
        )
    except BackendUnavailable as error:
        return render_template(
            "partials/section_error.html",
            section_title="Resumes",
            message=str(error),
            retry_url="/ui/resumes",
            retry_target="#resumes-section",
        )


def render_skills_section(
    notice: str | None = None,
    notice_tone: str = "success",
) -> str:
    try:
        profiles = fetch_collection("/api/v1/profiles")
        skills = fetch_collection("/api/v1/skills")
        profile_map = {
            profile["id"]: profile.get("full_name", f"Profile {profile['id']}")
            for profile in profiles
        }
        return render_template(
            "partials/skills_section.html",
            profiles=profiles,
            skills=skills,
            profile_map=profile_map,
            notice=notice,
            notice_tone=notice_tone,
        )
    except BackendUnavailable as error:
        return render_template(
            "partials/section_error.html",
            section_title="Candidate Skills",
            message=str(error),
            retry_url="/ui/skills",
            retry_target="#skills-section",
        )


def parse_feedback_sections(feedback: str) -> dict[str, list[str]]:
    canonical_headings = {
        "strengths": "Strengths",
        "skill gaps": "Skill Gaps",
        "skillgaps": "Skill Gaps",
        "recommended actions": "Recommended Actions",
        "information missing": "Information Missing",
    }
    result: dict[str, list[str]] = {
        "Strengths": [],
        "Skill Gaps": [],
        "Recommended Actions": [],
        "Information Missing": [],
    }
    current_heading: str | None = None

    for raw_line in feedback.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        heading_key = line.rstrip(":").strip().lower()
        if heading_key in canonical_headings:
            current_heading = canonical_headings[heading_key]
            continue

        if current_heading:
            item = line
            if item.startswith(("-", "•", "*")):
                item = item[1:].strip()
            if item:
                result[current_heading].append(item)

    return result


@app.get("/")
def index():
    return render_template(
        "index.html",
        backend_api_url=BACKEND_API_URL,
    )


@app.get("/health")
def health():
    return jsonify(
        {"status": "healthy", "service": "student-2-frontend"}
    ), 200


@app.get("/ready")
def ready():
    try:
        payload, status = backend_request("GET", "/ready")
    except BackendUnavailable as error:
        return jsonify(
            {
                "status": "not-ready",
                "service": "student-2-frontend",
                "error": str(error),
            }
        ), 503

    if status != 200:
        return jsonify(
            {
                "status": "not-ready",
                "service": "student-2-frontend",
                "backend": payload,
            }
        ), 503

    return jsonify(
        {
            "status": "ready",
            "service": "student-2-frontend",
            "backend": payload,
        }
    ), 200


@app.get("/ui/status")
def ui_status():
    try:
        backend_payload, backend_status = backend_request("GET", "/ready")
        ai_payload, ai_status = backend_request("GET", "/api/v1/ai/status")

        database_ready = (
            backend_status == 200
            and isinstance(backend_payload, dict)
            and backend_payload.get("status") == "ready"
        )
        ai_ready = (
            ai_status == 200
            and isinstance(ai_payload, dict)
            and ai_payload.get("configured_model_available") is True
        )

        return render_template(
            "partials/status_panel.html",
            backend_ready=backend_status == 200,
            database_ready=database_ready,
            ai_ready=ai_ready,
            model=(
                ai_payload.get("configured_model", "Not configured")
                if isinstance(ai_payload, dict)
                else "Not configured"
            ),
            status_message=None,
        )
    except BackendUnavailable as error:
        return render_template(
            "partials/status_panel.html",
            backend_ready=False,
            database_ready=False,
            ai_ready=False,
            model="Unavailable",
            status_message=str(error),
        )


@app.get("/ui/profiles")
def ui_profiles():
    return render_profiles_section()


@app.post("/ui/profiles")
def ui_create_profile():
    body = {
        "full_name": request.form.get("full_name", "").strip(),
        "email": request.form.get("email", "").strip(),
        "target_role": request.form.get("target_role", "").strip(),
        "career_summary": request.form.get("career_summary", "").strip(),
    }

    try:
        payload, status = backend_request(
            "POST", "/api/v1/profiles", json_body=body
        )
        if status == 201:
            html = render_profiles_section(
                f"Profile created for {payload.get('full_name', 'candidate')}."
            )
            return response_with_trigger(html, "profileDataChanged")

        return response_with_trigger(
            render_profiles_section(
                error_message(payload, "Unable to create profile."),
                "error",
            )
        )
    except BackendUnavailable as error:
        return response_with_trigger(
            render_profiles_section(str(error), "error")
        )


@app.get("/ui/profiles/<int:profile_id>/edit")
def ui_edit_profile_form(profile_id: int):
    try:
        profile, error = fetch_item(f"/api/v1/profiles/{profile_id}")
        if error or profile is None:
            return render_template(
                "partials/inline_error.html",
                message=error or "Profile not found.",
            )
        return render_template(
            "partials/profile_edit_form.html", profile=profile
        )
    except BackendUnavailable as error:
        return render_template(
            "partials/inline_error.html", message=str(error)
        )


@app.put("/ui/profiles/<int:profile_id>")
def ui_update_profile(profile_id: int):
    body = {
        "full_name": request.form.get("full_name", "").strip(),
        "email": request.form.get("email", "").strip(),
        "target_role": request.form.get("target_role", "").strip(),
        "career_summary": request.form.get("career_summary", "").strip(),
    }

    try:
        payload, status = backend_request(
            "PUT", f"/api/v1/profiles/{profile_id}", json_body=body
        )
        if status == 200:
            html = render_profiles_section(
                f"Profile updated for {payload.get('full_name', 'candidate')}."
            )
            return response_with_trigger(html, "profileDataChanged")

        return response_with_trigger(
            render_profiles_section(
                error_message(payload, "Unable to update profile."),
                "error",
            )
        )
    except BackendUnavailable as error:
        return response_with_trigger(
            render_profiles_section(str(error), "error")
        )


@app.delete("/ui/profiles/<int:profile_id>")
def ui_delete_profile(profile_id: int):
    try:
        payload, status = backend_request(
            "DELETE", f"/api/v1/profiles/{profile_id}"
        )
        if status == 200:
            html = render_profiles_section(
                payload.get("message", "Profile deleted successfully.")
            )
            return response_with_trigger(html, "profileDataChanged")

        return response_with_trigger(
            render_profiles_section(
                error_message(payload, "Unable to delete profile."),
                "error",
            )
        )
    except BackendUnavailable as error:
        return response_with_trigger(
            render_profiles_section(str(error), "error")
        )


@app.get("/ui/resumes")
def ui_resumes():
    return render_resumes_section()


@app.post("/ui/resumes")
def ui_create_resume():
    try:
        body = {
            "candidate_profile_id": positive_integer(
                request.form.get("candidate_profile_id"),
                "candidate_profile_id",
            ),
            "title": request.form.get("title", "").strip(),
            "content": request.form.get("content", "").strip(),
            "is_primary": 1 if request.form.get("is_primary") else 0,
        }
    except ValueError as error:
        return response_with_trigger(
            render_resumes_section(str(error), "error")
        )

    try:
        payload, status = backend_request(
            "POST", "/api/v1/resumes", json_body=body
        )
        if status == 201:
            html = render_resumes_section(
                f"Resume created: {payload.get('title', 'Untitled resume')}."
            )
            return response_with_trigger(html, "resumeDataChanged")

        return response_with_trigger(
            render_resumes_section(
                error_message(payload, "Unable to create resume."),
                "error",
            )
        )
    except BackendUnavailable as error:
        return response_with_trigger(
            render_resumes_section(str(error), "error")
        )


@app.get("/ui/resumes/<int:resume_id>/edit")
def ui_edit_resume_form(resume_id: int):
    try:
        resume, error = fetch_item(f"/api/v1/resumes/{resume_id}")
        if error or resume is None:
            return render_template(
                "partials/inline_error.html",
                message=error or "Resume not found.",
            )
        profiles = fetch_collection("/api/v1/profiles")
        return render_template(
            "partials/resume_edit_form.html",
            resume=resume,
            profiles=profiles,
        )
    except BackendUnavailable as error:
        return render_template(
            "partials/inline_error.html", message=str(error)
        )


@app.put("/ui/resumes/<int:resume_id>")
def ui_update_resume(resume_id: int):
    try:
        body = {
            "candidate_profile_id": positive_integer(
                request.form.get("candidate_profile_id"),
                "candidate_profile_id",
            ),
            "title": request.form.get("title", "").strip(),
            "content": request.form.get("content", "").strip(),
            "is_primary": 1 if request.form.get("is_primary") else 0,
        }
    except ValueError as error:
        return response_with_trigger(
            render_resumes_section(str(error), "error")
        )

    try:
        payload, status = backend_request(
            "PUT", f"/api/v1/resumes/{resume_id}", json_body=body
        )
        if status == 200:
            html = render_resumes_section(
                f"Resume updated: {payload.get('title', 'Untitled resume')}."
            )
            return response_with_trigger(html, "resumeDataChanged")

        return response_with_trigger(
            render_resumes_section(
                error_message(payload, "Unable to update resume."),
                "error",
            )
        )
    except BackendUnavailable as error:
        return response_with_trigger(
            render_resumes_section(str(error), "error")
        )


@app.delete("/ui/resumes/<int:resume_id>")
def ui_delete_resume(resume_id: int):
    try:
        payload, status = backend_request(
            "DELETE", f"/api/v1/resumes/{resume_id}"
        )
        if status == 200:
            html = render_resumes_section(
                payload.get("message", "Resume deleted successfully.")
            )
            return response_with_trigger(html, "resumeDataChanged")

        return response_with_trigger(
            render_resumes_section(
                error_message(payload, "Unable to delete resume."),
                "error",
            )
        )
    except BackendUnavailable as error:
        return response_with_trigger(
            render_resumes_section(str(error), "error")
        )


@app.get("/ui/skills")
def ui_skills():
    return render_skills_section()


@app.post("/ui/skills")
def ui_create_skill():
    try:
        body = {
            "candidate_profile_id": positive_integer(
                request.form.get("candidate_profile_id"),
                "candidate_profile_id",
            ),
            "skill_name": request.form.get("skill_name", "").strip(),
            "proficiency_level": request.form.get(
                "proficiency_level", ""
            ).strip(),
            "years_experience": non_negative_number(
                request.form.get("years_experience"),
                "years_experience",
            ),
        }
    except ValueError as error:
        return response_with_trigger(
            render_skills_section(str(error), "error")
        )

    try:
        payload, status = backend_request(
            "POST", "/api/v1/skills", json_body=body
        )
        if status == 201:
            html = render_skills_section(
                f"Skill created: {payload.get('skill_name', 'Skill')}."
            )
            return response_with_trigger(html, "skillDataChanged")

        return response_with_trigger(
            render_skills_section(
                error_message(payload, "Unable to create skill."),
                "error",
            )
        )
    except BackendUnavailable as error:
        return response_with_trigger(
            render_skills_section(str(error), "error")
        )


@app.get("/ui/skills/<int:skill_id>/edit")
def ui_edit_skill_form(skill_id: int):
    try:
        skill, error = fetch_item(f"/api/v1/skills/{skill_id}")
        if error or skill is None:
            return render_template(
                "partials/inline_error.html",
                message=error or "Skill not found.",
            )
        profiles = fetch_collection("/api/v1/profiles")
        return render_template(
            "partials/skill_edit_form.html",
            skill=skill,
            profiles=profiles,
        )
    except BackendUnavailable as error:
        return render_template(
            "partials/inline_error.html", message=str(error)
        )


@app.put("/ui/skills/<int:skill_id>")
def ui_update_skill(skill_id: int):
    try:
        body = {
            "candidate_profile_id": positive_integer(
                request.form.get("candidate_profile_id"),
                "candidate_profile_id",
            ),
            "skill_name": request.form.get("skill_name", "").strip(),
            "proficiency_level": request.form.get(
                "proficiency_level", ""
            ).strip(),
            "years_experience": non_negative_number(
                request.form.get("years_experience"),
                "years_experience",
            ),
        }
    except ValueError as error:
        return response_with_trigger(
            render_skills_section(str(error), "error")
        )

    try:
        payload, status = backend_request(
            "PUT", f"/api/v1/skills/{skill_id}", json_body=body
        )
        if status == 200:
            html = render_skills_section(
                f"Skill updated: {payload.get('skill_name', 'Skill')}."
            )
            return response_with_trigger(html, "skillDataChanged")

        return response_with_trigger(
            render_skills_section(
                error_message(payload, "Unable to update skill."),
                "error",
            )
        )
    except BackendUnavailable as error:
        return response_with_trigger(
            render_skills_section(str(error), "error")
        )


@app.delete("/ui/skills/<int:skill_id>")
def ui_delete_skill(skill_id: int):
    try:
        payload, status = backend_request(
            "DELETE", f"/api/v1/skills/{skill_id}"
        )
        if status == 200:
            html = render_skills_section(
                payload.get("message", "Skill deleted successfully.")
            )
            return response_with_trigger(html, "skillDataChanged")

        return response_with_trigger(
            render_skills_section(
                error_message(payload, "Unable to delete skill."),
                "error",
            )
        )
    except BackendUnavailable as error:
        return response_with_trigger(
            render_skills_section(str(error), "error")
        )


@app.get("/ui/ai/form")
def ui_ai_form():
    try:
        profiles = fetch_collection("/api/v1/profiles")
        selected_profile_id = profiles[0]["id"] if profiles else None
        resumes = (
            fetch_collection(
                "/api/v1/resumes",
                params={"candidate_profile_id": selected_profile_id},
            )
            if selected_profile_id
            else []
        )
        return render_template(
            "partials/ai_form.html",
            profiles=profiles,
            resumes=resumes,
            selected_profile_id=selected_profile_id,
        )
    except BackendUnavailable as error:
        return render_template(
            "partials/section_error.html",
            section_title="AI Resume Feedback",
            message=str(error),
            retry_url="/ui/ai/form",
            retry_target="#ai-form-panel",
        )


@app.get("/ui/ai/resume-options")
def ui_ai_resume_options():
    try:
        profile_id = positive_integer(
            request.args.get("profile_id"), "profile_id"
        )
        resumes = fetch_collection(
            "/api/v1/resumes",
            params={"candidate_profile_id": profile_id},
        )
        return render_template(
            "partials/ai_resume_options.html", resumes=resumes
        )
    except (ValueError, BackendUnavailable) as error:
        return render_template(
            "partials/ai_resume_options.html",
            resumes=[],
            error_message=str(error),
        )


@app.post("/ui/ai/resume-feedback")
def ui_ai_resume_feedback():
    try:
        profile_id = positive_integer(
            request.form.get("profile_id"), "profile_id"
        )
        resume_id = positive_integer(
            request.form.get("resume_id"), "resume_id"
        )
    except ValueError as error:
        return render_template(
            "partials/ai_result.html",
            error_message=str(error),
            feedback=None,
        )

    body = {
        "profile_id": profile_id,
        "resume_id": resume_id,
        "job_description": request.form.get(
            "job_description", ""
        ).strip(),
    }

    try:
        payload, status = backend_request(
            "POST",
            "/api/v1/ai/resume-feedback",
            json_body=body,
            timeout=AI_TIMEOUT,
        )
    except BackendUnavailable as error:
        return render_template(
            "partials/ai_result.html",
            error_message=str(error),
            feedback=None,
        )

    if status != 200 or not isinstance(payload, dict):
        return render_template(
            "partials/ai_result.html",
            error_message=error_message(
                payload, "AI feedback could not be generated."
            ),
            feedback=None,
        )

    feedback = payload.get("feedback", "")
    sections = parse_feedback_sections(feedback)

    return render_template(
        "partials/ai_result.html",
        error_message=None,
        feedback=feedback,
        feedback_sections=sections,
        model=payload.get("model", "Unknown model"),
        grounding=payload.get("grounding", ""),
        context_summary=payload.get("context_summary", {}),
    )


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "Frontend route not found."}), 404


@app.errorhandler(405)
def method_not_allowed(_error):
    return jsonify({"error": "Method not allowed."}), 405


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
