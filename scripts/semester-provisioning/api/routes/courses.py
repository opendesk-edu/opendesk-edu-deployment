# SPDX-FileCopyrightText: 2024 Zentrum für Digitale Souveränität der öffentlichen Verwaltung (ZenDiS) GmbH
# SPDX-FileCopyrightText: 2024 Bundesministerium des Innern und für Heimat, PG ZenDiS "Projektgruppe für Aufbau ZenDiS"
# SPDX-License-Identifier: Apache-2.0
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Query, status
from api.models.course import (
    Course,
    CourseCreate,
    CourseBulkCreate,
    CourseUpdate,
    CourseList,
    CourseStatus,
    LMSPlatform,
    Enrollment,
    EnrollmentCreate,
    EnrollmentBulkCreate,
    ErrorResponse,
)
from api.utils.ilias_client import ILIASClient
from api.utils.moodle_client import MoodleClient
from api.utils.keycloak_client import KeycloakClient
from api.utils.marvin_client import MarvinClient
from api.utils.hisinone_client import HISinOneClient

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])

_courses_db: dict[str, Course] = {}
_enrollments_db: dict[str, Enrollment] = {}


async def _get_lms_client(lms: LMSPlatform):
    if lms == LMSPlatform.ILIAS:
        return ILIASClient()
    return MoodleClient()


@router.post(
    "",
    response_model=Course,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Course created successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request data"},
        500: {"model": ErrorResponse, "description": "LMS or Keycloak error"},
    },
)
async def create_course(course: CourseCreate) -> Course:
    course_id = f"crs_{uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)

    lms_course_id = None
    async with await _get_lms_client(course.lms) as client:
        result = await client.create_course(
            title=course.title,
            category_id=course.category,
        )
        lms_course_id = result.get("ilias_course_id") or result.get("moodle_course_id")

    async with KeycloakClient() as kc:
        await kc.create_course_groups(course_id, course.semester_id)

    new_course = Course(
        course_id=course_id,
        lms_course_id=lms_course_id,
        semester_id=course.semester_id,
        title=course.title,
        title_en=course.title_en,
        course_code=course.course_code,
        instructor_ids=course.instructor_ids,
        expected_enrollment=course.expected_enrollment,
        lms=course.lms,
        category=course.category,
        status=CourseStatus.ACTIVE,
        created_at=now,
    )
    _courses_db[course_id] = new_course
    return new_course


@router.post(
    "/bulk-create",
    response_model=list[Course],
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Courses created successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request data"},
    },
)
async def bulk_create_courses(request: CourseBulkCreate) -> list[Course]:
    created_courses = []
    for course_data in request.courses:
        course = await create_course(course_data)
        created_courses.append(course)
    return created_courses


@router.post(
    "/sync",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Courses synced successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request data"},
        500: {"model": ErrorResponse, "description": "Sync operation failed"},
    },
)
async def sync_courses(request: dict[str, str]) -> dict[str, Any]:
    """Sync courses from campus management system (HISinOne or Marvin).

    Args:
        request: Dictionary with semester_id and source keys

    Returns:
        Dictionary with sync statistics
    """
    semester_id = request.get("semester_id")
    source = request.get("source", "marvin").lower()

    if not semester_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="semester_id is required",
        )

    if source not in ["hisinone", "marvin"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source: {source}. Must be 'hisinone' or 'marvin'",
        )

    logger.info(f"Syncing courses for semester {semester_id} from {source}")

    synced_count = 0
    created_count = 0
    updated_count = 0
    errors: list[str] = []

    try:
        # Get courses from campus management
        if source == "marvin":
            async with MarvinClient() as client:
                courses_data = await client.get_courses(semester_id)
        else:  # hisinone
            async with HISinOneClient() as client:
                courses_data = await client.get_courses(semester_id)

        # Normalize courses_data to list
        if isinstance(courses_data, dict) and "data" in courses_data:
            courses = courses_data["data"]
        elif isinstance(courses_data, list):
            courses = courses_data
        else:
            courses = []

        logger.info(f"Retrieved {len(courses)} courses from {source}")

        # Process each course
        for course_dict in courses:
            try:
                # Extract course data
                course_id_ext = course_dict.get("id") or course_dict.get("course_id")
                title = course_dict.get("title", "")
                title_en = course_dict.get("title_en")
                course_code = course_dict.get("course_code", "")
                instructor_ids = course_dict.get("instructor_ids", [])
                expected_enrollment = course_dict.get("expected_enrollment")
                lms_platform = course_dict.get("lms", "ilias").lower()

                # Map to LMSPlatform enum
                if lms_platform == "moodle":
                    lms = LMSPlatform.MOODLE
                else:
                    lms = LMSPlatform.ILIAS

                # Check if course already exists
                existing_course = None
                for existing in _courses_db.values():
                    if (
                        existing.semester_id == semester_id
                        and existing.course_code == course_code
                    ):
                        existing_course = existing
                        break

                now = datetime.now(timezone.utc)

                if existing_course:
                    # Update existing course
                    existing_course.title = title
                    existing_course.title_en = title_en or existing_course.title_en
                    existing_course.instructor_ids = instructor_ids
                    existing_course.expected_enrollment = expected_enrollment
                    existing_course.updated_at = now
                    _courses_db[existing_course.course_id] = existing_course
                    updated_count += 1
                    logger.debug(f"Updated course {course_code} ({title})")
                else:
                    # Create new course
                    new_course_id = f"crs_{uuid4().hex[:12]}"

                    # Create course in LMS
                    lms_course_id = None
                    try:
                        async with await _get_lms_client(lms) as client:
                            result = await client.create_course(
                                title=title,
                                category_id=course_dict.get("category"),
                            )
                            lms_course_id = result.get("ilias_course_id") or result.get(
                                "moodle_course_id"
                            )
                    except Exception as e:
                        logger.error(
                            f"Failed to create LMS course for {course_code}: {e}"
                        )
                        errors.append(
                            f"LMS creation failed for {course_code}: {str(e)}"
                        )

                    # Create course groups in Keycloak
                    try:
                        async with KeycloakClient() as kc:
                            await kc.create_course_groups(new_course_id, semester_id)
                    except Exception as e:
                        logger.error(
                            f"Failed to create Keycloak groups for {course_code}: {e}"
                        )
                        errors.append(
                            f"Keycloak group creation failed for {course_code}: {str(e)}"
                        )

                    new_course = Course(
                        course_id=new_course_id,
                        lms_course_id=lms_course_id,
                        semester_id=semester_id,
                        title=title,
                        title_en=title_en,
                        course_code=course_code,
                        instructor_ids=instructor_ids,
                        expected_enrollment=expected_enrollment,
                        lms=lms,
                        category=course_dict.get("category"),
                        status=CourseStatus.ACTIVE,
                        created_at=now,
                    )
                    _courses_db[new_course_id] = new_course
                    created_count += 1
                    logger.debug(f"Created course {course_code} ({title})")

                synced_count += 1

            except Exception as e:
                error_msg = f"Failed to process course {course_dict.get('course_code', 'unknown')}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(
            f"Sync completed: {synced_count} synced, {created_count} created, "
            f"{updated_count} updated, {len(errors)} errors"
        )

        return {
            "synced": synced_count,
            "created": created_count,
            "updated": updated_count,
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"Sync operation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync operation failed: {str(e)}",
        )


@router.get(
    "/{course_id}",
    response_model=Course,
    responses={
        200: {"description": "Course details"},
        404: {"model": ErrorResponse, "description": "Course not found"},
    },
)
async def get_course(course_id: str) -> Course:
    if course_id not in _courses_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found",
        )
    return _courses_db[course_id]


@router.get(
    "",
    response_model=CourseList,
    responses={200: {"description": "List of courses"}},
)
async def list_courses(
    semester_id: Optional[str] = Query(None, description="Filter by semester ID"),
    status_filter: Optional[CourseStatus] = Query(
        None, alias="status", description="Filter by status"
    ),
    lms: Optional[LMSPlatform] = Query(None, description="Filter by LMS platform"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> CourseList:
    filtered = list(_courses_db.values())

    if semester_id:
        filtered = [c for c in filtered if c.semester_id == semester_id]
    if status_filter:
        filtered = [c for c in filtered if c.status == status_filter]
    if lms:
        filtered = [c for c in filtered if c.lms == lms]

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size

    return CourseList(
        courses=filtered[start:end],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.put(
    "/{course_id}",
    response_model=Course,
    responses={
        200: {"description": "Course updated successfully"},
        404: {"model": ErrorResponse, "description": "Course not found"},
    },
)
async def update_course(course_id: str, course_update: CourseUpdate) -> Course:
    if course_id not in _courses_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found",
        )

    existing = _courses_db[course_id]
    update_data = course_update.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(existing, field, value)

    existing.updated_at = datetime.now(timezone.utc)
    _courses_db[course_id] = existing
    return existing


@router.delete(
    "/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Course soft-deleted successfully"},
        404: {"model": ErrorResponse, "description": "Course not found"},
    },
)
async def delete_course(course_id: str) -> None:
    if course_id not in _courses_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found",
        )

    _courses_db[course_id].status = CourseStatus.DELETED
    _courses_db[course_id].updated_at = datetime.now(timezone.utc)


@router.post(
    "/{course_id}/enrollments",
    response_model=list[Enrollment],
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Enrollments created successfully"},
        404: {"model": ErrorResponse, "description": "Course not found"},
    },
)
@router.post(
    "/{course_id}/bulk-add",
    response_model=list[Enrollment],
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Enrollments created successfully"},
        404: {"model": ErrorResponse, "description": "Course not found"},
    },
    summary="Bulk add enrollments / Masseneinschreibungen hinzufügen",
    description="Enroll multiple users in a course at once. / Mehrere Benutzer gleichzeitig in einen Kurs einschreiben.",
)
async def bulk_enroll_users(
    course_id: str, request: EnrollmentBulkCreate
) -> list[Enrollment]:
    if course_id not in _courses_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found",
        )

    course = _courses_db[course_id]
    created_enrollments = []
    now = datetime.now(timezone.utc)

    async with await _get_lms_client(course.lms) as client:
        for enrollment_data in request.enrollments:
            enrollment_id = f"enr_{uuid4().hex[:12]}"
            await client.enroll_user(
                course_id=course.lms_course_id or course_id,
                user_id=enrollment_data.user_id,
                role=enrollment_data.role,
            )

            enrollment = Enrollment(
                enrollment_id=enrollment_id,
                course_id=course_id,
                user_id=enrollment_data.user_id,
                role=enrollment_data.role,
                created_at=now,
            )
            _enrollments_db[enrollment_id] = enrollment
            created_enrollments.append(enrollment)

    return created_enrollments


"""Bulk-add compatibility route removed in favor of dual-endpoint mapping on bulk_enroll_users."""
