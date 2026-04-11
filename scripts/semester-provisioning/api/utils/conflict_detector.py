# SPDX-FileCopyrightText: 2024 Zentrum für Digitale Souveränität der öffentlichen Verwaltung (ZenDiS) GmbH
# SPDX-FileCopyrightText: 2024 Bundesministerium des Innern und für Heimat, PG ZenDiS "Projektgruppe für Aufbau ZenDiS"
# SPDX-License-Identifier: Apache-2.0
"""
Conflict detection engine for enrollment management.
Konflikterkennungsmaschine für die Einschreibungsverwaltung.

This module provides the ConflictDetector class that detects various types
of enrollment conflicts including schedule overlaps, capacity issues,
and double enrollments.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from api.models.enrollment import Enrollment, EnrollmentStatus
from api.models.course import Course
import logging

logger = logging.getLogger(__name__)


class ConflictSeverity(str, Enum):
    """
    Severity levels for conflicts.
    Schweregrade für Konflikte.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ConflictType(str, Enum):
    """
    Types of enrollment conflicts.
    Arten von Einschreibungskonflikten.
    """

    SCHEDULE = "schedule"
    CAPACITY = "capacity"
    DOUBLE_ENROLLMENT = "double_enrollment"


@dataclass
class ScheduleConflict:
    """
    Schedule conflict between courses.
    Zeitplan-Konflikt zwischen Kursen.
    """

    student_id: str
    course_ids: list[str]
    conflict_type: ConflictType = ConflictType.SCHEDULE
    severity: ConflictSeverity = ConflictSeverity.WARNING
    description: str = ""


@dataclass
class CapacityConflict:
    """
    Capacity conflict (over-enrolled course).
    Kapazitätskonflikt (Überbuchter Kurs).
    """

    course_id: str
    course_title: str
    expected: int
    actual: int
    overflow: int
    conflict_type: ConflictType = ConflictType.CAPACITY
    severity: ConflictSeverity = ConflictSeverity.ERROR
    description: str = ""


@dataclass
class DoubleEnrollment:
    """
    Double enrollment conflict (same student in same course with different roles).
    Doppelt-Einschreibungskonflikt (gleicher Student im gleichen Kurs mit verschiedenen Rollen).
    """

    student_id: str
    course_id: str
    course_title: str
    roles: list[str]
    conflict_type: ConflictType = ConflictType.DOUBLE_ENROLLMENT
    severity: ConflictSeverity = ConflictSeverity.WARNING
    description: str = ""


class ConflictDetector:
    """
    Engine for detecting enrollment conflicts.
    Maschine zur Erkennung von Einschreibungskonflikten.

    Detects:
    - Schedule conflicts: Students enrolled in overlapping courses
    - Capacity conflicts: Courses exceeding expected enrollment
    - Double enrollments: Students enrolled multiple times in same course
    """

    def __init__(
        self, courses_db: dict[str, Course], enrollments_db: dict[str, Enrollment]
    ):
        """
        Initialize conflict detector.

        Args:
            courses_db: Reference to courses database
            enrollments_db: Reference to enrollments database
        """
        self._courses_db = courses_db
        self._enrollments_db = enrollments_db

    def detect_schedule_conflicts(
        self, semester_id: str, course_ids: list[str] | None = None
    ) -> list[ScheduleConflict]:
        """
        Detect schedule conflicts between courses.

        For each pair of courses, check if any student is enrolled in both.
        In a production system, this would also check for time overlap.

        Args:
            semester_id: Semester to check
            course_ids: Optional list of course IDs to check (all semester courses if None)

        Returns:
            List of schedule conflicts
        """
        conflicts: list[ScheduleConflict] = []

        # Get courses to check
        if course_ids:
            courses_to_check = [
                c for c in self._courses_db.values() if c.course_id in course_ids
            ]
        else:
            courses_to_check = [
                c for c in self._courses_db.values() if c.semester_id == semester_id
            ]

        logger.info(
            f"Checking schedule conflicts for {len(courses_to_check)} courses in semester {semester_id}"
        )

        # Build enrollment mapping: student_id -> list of course_ids
        student_enrollments: dict[str, list[str]] = {}
        for enrollment in self._enrollments_db.values():
            if (
                enrollment.status == EnrollmentStatus.ACTIVE
                and enrollment.course_id in [c.course_id for c in courses_to_check]
            ):
                if enrollment.user_id not in student_enrollments:
                    student_enrollments[enrollment.user_id] = []
                student_enrollments[enrollment.user_id].append(enrollment.course_id)

        # Find students enrolled in multiple courses
        for student_id, enrolled_course_ids in student_enrollments.items():
            if len(enrolled_course_ids) > 1:
                # In production, check time overlap here
                # For now, flag any multiple enrollment as potential conflict
                conflict = ScheduleConflict(
                    student_id=student_id,
                    course_ids=enrolled_course_ids,
                    description=f"Student {student_id} enrolled in {len(enrolled_course_ids)} courses",
                )
                conflicts.append(conflict)
                logger.debug(
                    f"Schedule conflict found: student {student_id} in courses {enrolled_course_ids}"
                )

        return conflicts

    def detect_capacity_conflicts(
        self, semester_id: str, course_ids: list[str] | None = None
    ) -> list[CapacityConflict]:
        """
        Detect capacity conflicts (courses exceeding expected enrollment).

        Args:
            semester_id: Semester to check
            course_ids: Optional list of course IDs to check (all semester courses if None)

        Returns:
            List of capacity conflicts
        """
        conflicts: list[CapacityConflict] = []

        # Get courses to check
        if course_ids:
            courses_to_check = [
                c
                for c in self._courses_db.values()
                if c.course_id in course_ids and c.expected_enrollment is not None
            ]
        else:
            courses_to_check = [
                c
                for c in self._courses_db.values()
                if c.semester_id == semester_id and c.expected_enrollment is not None
            ]

        logger.info(
            f"Checking capacity conflicts for {len(courses_to_check)} courses in semester {semester_id}"
        )

        # Count actual enrollments for each course
        for course in courses_to_check:
            actual_enrollment = sum(
                1
                for e in self._enrollments_db.values()
                if e.course_id == course.course_id
                and e.status == EnrollmentStatus.ACTIVE
            )

            if actual_enrollment > course.expected_enrollment:  # type: ignore
                overflow = actual_enrollment - course.expected_enrollment  # type: ignore
                conflict = CapacityConflict(
                    course_id=course.course_id,
                    course_title=course.title,
                    expected=course.expected_enrollment,  # type: ignore
                    actual=actual_enrollment,
                    overflow=overflow,
                    description=f"Course {course.title} has {overflow} more students than expected",
                )
                conflicts.append(conflict)
                logger.debug(
                    f"Capacity conflict found: {course.title} ({actual_enrollment}/{course.expected_enrollment})"
                )

        return conflicts

    def detect_double_enrollments(
        self, semester_id: str, course_id: str | None = None
    ) -> list[DoubleEnrollment]:
        """
        Detect double enrollments (same student in same course with different roles).

        Args:
            semester_id: Semester to check
            course_id: Optional specific course ID to check (all semester courses if None)

        Returns:
            List of double enrollment conflicts
        """
        conflicts: list[DoubleEnrollment] = []

        # Get courses to check
        if course_id:
            courses_to_check = [
                c for c in self._courses_db.values() if c.course_id == course_id
            ]
        else:
            courses_to_check = [
                c for c in self._courses_db.values() if c.semester_id == semester_id
            ]

        logger.info(
            f"Checking double enrollments for {len(courses_to_check)} courses in semester {semester_id}"
        )

        # Build enrollment mapping: (course_id, user_id) -> list of roles
        enrollment_roles: dict[tuple[str, str], list[str]] = {}
        for enrollment in self._enrollments_db.values():
            if (
                enrollment.status == EnrollmentStatus.ACTIVE
                and enrollment.course_id in [c.course_id for c in courses_to_check]
            ):
                key = (enrollment.course_id, enrollment.user_id)
                if key not in enrollment_roles:
                    enrollment_roles[key] = []
                enrollment_roles[key].append(enrollment.role.value)

        # Find double enrollments
        for (course_id, user_id), roles in enrollment_roles.items():
            if len(roles) > 1:
                course = self._courses_db.get(course_id)
                course_title = course.title if course else "Unknown"
                conflict = DoubleEnrollment(
                    student_id=user_id,
                    course_id=course_id,
                    course_title=course_title,
                    roles=roles,
                    description=f"Student {user_id} has multiple roles ({', '.join(roles)}) in course {course_title}",
                )
                conflicts.append(conflict)
                logger.debug(
                    f"Double enrollment found: user {user_id} in course {course_id} with roles {roles}"
                )

        return conflicts
