# SPDX-FileCopyrightText: 2024 Zentrum für Digitale Souveränität der öffentlichen Verwaltung (ZenDiS) GmbH
# SPDX-FileCopyrightText: 2024 Bundesministerium des Innern und für Heimat, PG ZenDiS "Projektgruppe für Aufbau ZenDiS"
# SPDX-License-Identifier: Apache-2.0
"""
Enrollment synchronization engine for campus management systems.
Einschreibungssynchronisierungsmaschine für Campus-Management-Systeme.

This module provides the EnrollmentSyncEngine class that synchronizes enrollment
data from campus management systems (HISinOne or Marvin) with the local database.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import logging

from api.models.enrollment import Enrollment, EnrollmentStatus, EnrollmentRole
from api.models.course import Course
from api.utils.hisinone_client import HISinOneClient
from api.utils.marvin_client import MarvinClient

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """
    Result of an enrollment sync operation.
    Ergebnis einer Einschreibungssynchronisation.
    """

    semester_id: str = ""
    source: str = ""
    total_courses: int = 0
    added: int = 0
    withdrawn: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    synced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EnrollmentSyncEngine:
    """
    Engine for synchronizing enrollments from campus management systems.
    Maschine zur Synchronisierung von Einschreibungen aus Campus-Management-Systemen.

    Handles the complete sync workflow:
    1. Fetch courses for a semester from campus management
    2. For each course, fetch enrollments
    3. Compare with local database
    4. Add new enrollments, withdraw removed ones
    """

    def __init__(
        self, courses_db: dict[str, Course], enrollments_db: dict[str, Enrollment]
    ):
        """
        Initialize enrollment sync engine.

        Args:
            courses_db: Reference to courses database
            enrollments_db: Reference to enrollments database
        """
        self._courses_db = courses_db
        self._enrollments_db = enrollments_db

    async def sync_enrollments(
        self, semester_id: str, source: str = "marvin", dry_run: bool = False
    ) -> SyncResult:
        """
        Synchronize enrollments for a semester from campus management.

        Args:
            semester_id: Semester identifier (e.g., "2026ws")
            source: Campus management system ("hisinone" or "marvin")
            dry_run: If True, don't persist changes to database

        Returns:
            SyncResult with statistics
        """
        logger.info(f"Syncing enrollments for semester {semester_id} from {source}")

        result = SyncResult(semester_id=semester_id, source=source)

        # Validate source
        source = source.lower()
        if source not in ["hisinone", "marvin"]:
            result.errors.append(f"Invalid source: {source}")
            return result

        try:
            # Get courses for semester from campus management
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
            result.total_courses = len(courses)

            # Process each course
            for course_dict in courses:
                try:
                    # Extract course data
                    course_id_ext = course_dict.get("id") or course_dict.get(
                        "course_id"
                    )

                    # Find matching course in local database
                    local_course = None
                    for course in self._courses_db.values():
                        if (
                            course.semester_id == semester_id
                            and course.course_code == course_dict.get("course_code", "")
                        ):
                            local_course = course
                            break

                    if not local_course:
                        logger.warning(
                            f"Course {course_id_ext} not found in local database, skipping"
                        )
                        continue

                    # Get enrollments from campus management
                    if source == "marvin":
                        async with MarvinClient() as client:
                            campus_enrollments = await client.get_enrollments(
                                course_id_ext
                            )
                    else:  # hisinone
                        async with HISinOneClient() as client:
                            campus_enrollments = await client.get_enrollments(
                                course_id_ext
                            )

                    # Normalize campus_enrollments to list
                    if (
                        isinstance(campus_enrollments, dict)
                        and "data" in campus_enrollments
                    ):
                        campus_enrollments = campus_enrollments["data"]
                    elif isinstance(campus_enrollments, list):
                        campus_enrollments = campus_enrollments
                    else:
                        campus_enrollments = []

                    # Sync enrollments for this course
                    added, withdrawn = await self._sync_course_enrollments(
                        local_course.course_id, campus_enrollments, source, dry_run
                    )

                    result.added += added
                    result.withdrawn += withdrawn
                    result.unchanged += len(campus_enrollments) - added

                except Exception as e:
                    error_msg = f"Failed to sync course {course_dict.get('course_code', 'unknown')}: {str(e)}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)

            logger.info(
                f"Sync completed: {result.added} added, {result.withdrawn} withdrawn, "
                f"{result.unchanged} unchanged, {len(result.errors)} errors"
            )

        except Exception as e:
            error_msg = f"Sync operation failed: {str(e)}"
            logger.error(error_msg)
            result.errors.append(error_msg)

        return result

    async def _sync_course_enrollments(
        self,
        course_id: str,
        campus_enrollments: list[dict[str, Any]],
        source: str,
        dry_run: bool,
    ) -> tuple[int, int]:
        """
        Synchronize enrollments for a single course.

        Args:
            course_id: Local course identifier
            campus_enrollments: List of enrollments from campus management
            source: Campus management system name
            dry_run: If True, don't persist changes

        Returns:
            Tuple of (added_count, withdrawn_count)
        """
        added_count = 0
        withdrawn_count = 0

        # Get course details
        course = self._courses_db.get(course_id)
        if not course:
            logger.warning(f"Course {course_id} not found")
            return (0, 0)

        # Build set of active campus enrollments (user_id, role)
        campus_set = set()
        for enrollment_data in campus_enrollments:
            user_id = enrollment_data.get("student_id") or enrollment_data.get(
                "user_id"
            )
            role_str = enrollment_data.get("role", "student")
            role = (
                EnrollmentRole.STUDENT
                if role_str == "student"
                else EnrollmentRole.INSTRUCTOR
            )
            campus_set.add((user_id, role))

        # Get existing active enrollments for this course
        existing_enrollments: dict[str, Enrollment] = {}
        for enr_id, enrollment in self._enrollments_db.items():
            if (
                enrollment.course_id == course_id
                and enrollment.status == EnrollmentStatus.ACTIVE
            ):
                existing_enrollments[enrollment.user_id] = enrollment

        # Find enrollments to add (in campus but not local)
        for user_id, role in campus_set:
            if user_id not in existing_enrollments:
                # New enrollment - add it
                if not dry_run:
                    enrollment_id = f"enr_{user_id}_{course_id}"
                    now = datetime.now(timezone.utc)

                    new_enrollment = Enrollment(
                        enrollment_id=enrollment_id,
                        course_id=course_id,
                        user_id=user_id,
                        role=role,
                        status=EnrollmentStatus.ACTIVE,
                        created_at=now,
                    )
                    self._enrollments_db[enrollment_id] = new_enrollment

                added_count += 1
                logger.debug(f"Added enrollment: user {user_id} to course {course_id}")

        # Find enrollments to withdraw (in local but not campus)
        for user_id, enrollment in existing_enrollments.items():
            if (user_id, enrollment.role) not in campus_set:
                # Withdrawn enrollment - mark as WITHDRAWN
                if not dry_run:
                    enrollment.status = EnrollmentStatus.WITHDRAWN
                    enrollment.updated_at = datetime.now(timezone.utc)
                    self._enrollments_db[enrollment.enrollment_id] = enrollment

                withdrawn_count += 1
                logger.debug(
                    f"Withdrew enrollment: user {user_id} from course {course_id}"
                )

        return (added_count, withdrawn_count)
