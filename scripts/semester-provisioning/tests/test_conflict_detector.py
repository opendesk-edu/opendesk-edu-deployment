# SPDX-FileCopyrightText: 2024 Zentrum für Digitale Souveränität der öffentlichen Verwaltung (ZenDiS) GmbH
# SPDX-FileCopyrightText: 2024 Bundesministerium des Innern und für Heimat, PG ZenDiS "Projektgruppe für Aufbau ZenDiS"
# SPDX-License-Identifier: Apache-2.0
"""
Tests for conflict detection engine.
Tests für die Konflikterkennungsmaschine.
"""

import pytest
from datetime import datetime, timezone

from api.utils.conflict_detector import (
    ConflictDetector,
    ScheduleConflict,
    CapacityConflict,
    DoubleEnrollment,
    ConflictSeverity,
    ConflictType,
)
from api.models.enrollment import Enrollment, EnrollmentStatus, EnrollmentRole
from api.models.course import Course, CourseStatus, LMSPlatform


@pytest.fixture
def conflict_detector(mock_course_data):
    """Create a conflict detector with test databases."""
    courses_db = {}
    enrollments_db = {}

    # Add test courses
    course1 = Course(
        course_id="crs_001",
        lms_course_id="ilias_001",
        semester_id="2026ws",
        title="Introduction to Computer Science",
        course_code="INF-101",
        instructor_ids=[],
        expected_enrollment=30,
        lms=LMSPlatform.ILIAS,
        category="test",
        status=CourseStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    courses_db[course1.course_id] = course1

    course2 = Course(
        course_id="crs_002",
        lms_course_id="ilias_002",
        semester_id="2026ws",
        title="Mathematics I",
        course_code="MAT-101",
        instructor_ids=[],
        expected_enrollment=25,
        lms=LMSPlatform.ILIAS,
        category="test",
        status=CourseStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    courses_db[course2.course_id] = course2

    # Over-capacity course
    course3 = Course(
        course_id="crs_003",
        lms_course_id="ilias_003",
        semester_id="2026ws",
        title="Overbooked Course",
        course_code="OVF-101",
        instructor_ids=[],
        expected_enrollment=2,
        lms=LMSPlatform.ILIAS,
        category="test",
        status=CourseStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    courses_db[course3.course_id] = course3

    return ConflictDetector(courses_db, enrollments_db)


def test_detect_schedule_conflicts(conflict_detector):
    """Test detection of schedule conflicts (students enrolled in multiple courses)."""
    # Add student enrolled in two courses
    enrollment1 = Enrollment(
        enrollment_id="enr_001",
        course_id="crs_001",
        user_id="student-001",
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    conflict_detector._enrollments_db["enr_001"] = enrollment1

    enrollment2 = Enrollment(
        enrollment_id="enr_002",
        course_id="crs_002",
        user_id="student-001",
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    conflict_detector._enrollments_db["enr_002"] = enrollment2

    # Detect schedule conflicts
    conflicts = conflict_detector.detect_schedule_conflicts("2026ws")

    assert len(conflicts) == 1
    assert conflicts[0].student_id == "student-001"
    assert set(conflicts[0].course_ids) == {"crs_001", "crs_002"}
    assert conflicts[0].conflict_type == ConflictType.SCHEDULE
    assert conflicts[0].severity == ConflictSeverity.WARNING


def test_no_schedule_conflicts_for_single_enrollment(conflict_detector):
    """Test that single enrollment doesn't trigger schedule conflict."""
    # Add student enrolled in only one course
    enrollment1 = Enrollment(
        enrollment_id="enr_001",
        course_id="crs_001",
        user_id="student-001",
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    conflict_detector._enrollments_db["enr_001"] = enrollment1

    # Detect schedule conflicts
    conflicts = conflict_detector.detect_schedule_conflicts("2026ws")

    assert len(conflicts) == 0


def test_detect_capacity_conflicts(conflict_detector):
    """Test detection of capacity conflicts (over-enrolled courses)."""
    # Add 3 students to course with expected enrollment of 2
    for i in range(3):
        enrollment = Enrollment(
            enrollment_id=f"enr_00{i}",
            course_id="crs_003",
            user_id=f"student-{i}",
            role=EnrollmentRole.STUDENT,
            status=EnrollmentStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
        )
        conflict_detector._enrollments_db[enrollment.enrollment_id] = enrollment

    # Detect capacity conflicts
    conflicts = conflict_detector.detect_capacity_conflicts("2026ws")

    assert len(conflicts) == 1
    assert conflicts[0].course_id == "crs_003"
    assert conflicts[0].course_title == "Overbooked Course"
    assert conflicts[0].expected == 2
    assert conflicts[0].actual == 3
    assert conflicts[0].overflow == 1
    assert conflicts[0].conflict_type == ConflictType.CAPACITY
    assert conflicts[0].severity == ConflictSeverity.ERROR


def test_no_capacity_conflicts_at_expected_enrollment(conflict_detector):
    """Test that courses at or below expected enrollment don't trigger capacity conflict."""
    # Add 2 students to course with expected enrollment of 2
    for i in range(2):
        enrollment = Enrollment(
            enrollment_id=f"enr_00{i}",
            course_id="crs_003",
            user_id=f"student-{i}",
            role=EnrollmentRole.STUDENT,
            status=EnrollmentStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
        )
        conflict_detector._enrollments_db[enrollment.enrollment_id] = enrollment

    # Detect capacity conflicts
    conflicts = conflict_detector.detect_capacity_conflicts("2026ws")

    assert len(conflicts) == 0


def test_detect_double_enrollments(conflict_detector):
    """Test detection of double enrollments (same student, same course, different roles)."""
    # Add student enrolled twice in same course with different roles
    enrollment1 = Enrollment(
        enrollment_id="enr_001",
        course_id="crs_001",
        user_id="student-001",
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    conflict_detector._enrollments_db["enr_001"] = enrollment1

    enrollment2 = Enrollment(
        enrollment_id="enr_002",
        course_id="crs_001",
        user_id="student-001",
        role=EnrollmentRole.TUTOR,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    conflict_detector._enrollments_db["enr_002"] = enrollment2

    # Detect double enrollments
    conflicts = conflict_detector.detect_double_enrollments("2026ws")

    assert len(conflicts) == 1
    assert conflicts[0].student_id == "student-001"
    assert conflicts[0].course_id == "crs_001"
    assert conflicts[0].course_title == "Introduction to Computer Science"
    assert set(conflicts[0].roles) == {"student", "tutor"}
    assert conflicts[0].conflict_type == ConflictType.DOUBLE_ENROLLMENT
    assert conflicts[0].severity == ConflictSeverity.WARNING


def test_no_double_enrollments_for_single_role(conflict_detector):
    """Test that single enrollment doesn't trigger double enrollment conflict."""
    # Add student enrolled once in course
    enrollment1 = Enrollment(
        enrollment_id="enr_001",
        course_id="crs_001",
        user_id="student-001",
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    conflict_detector._enrollments_db["enr_001"] = enrollment1

    # Detect double enrollments
    conflicts = conflict_detector.detect_double_enrollments("2026ws")

    assert len(conflicts) == 0


def test_filter_by_conflict_type(conflict_detector):
    """Test filtering conflicts by type."""
    # Add test data for all conflict types
    # Schedule conflict
    enrollment1 = Enrollment(
        enrollment_id="enr_001",
        course_id="crs_001",
        user_id="student-001",
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    conflict_detector._enrollments_db["enr_001"] = enrollment1

    enrollment2 = Enrollment(
        enrollment_id="enr_002",
        course_id="crs_002",
        user_id="student-001",
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    conflict_detector._enrollments_db["enr_002"] = enrollment2

    # Capacity conflict
    for i in range(3):
        enrollment = Enrollment(
            enrollment_id=f"enr_cap_{i}",
            course_id="crs_003",
            user_id=f"student-cap-{i}",
            role=EnrollmentRole.STUDENT,
            status=EnrollmentStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
        )
        conflict_detector._enrollments_db[enrollment.enrollment_id] = enrollment

    # Test filtering by conflict type
    schedule_conflicts = conflict_detector.detect_schedule_conflicts("2026ws")
    capacity_conflicts = conflict_detector.detect_capacity_conflicts("2026ws")
    double_enrollments = conflict_detector.detect_double_enrollments("2026ws")

    assert len(schedule_conflicts) == 1
    assert len(capacity_conflicts) == 1
    assert len(double_enrollments) == 0


def test_withdrawn_enrollments_not_in_conflicts(conflict_detector):
    """Test that withdrawn enrollments don't trigger conflicts."""
    # Add withdrawn enrollment
    enrollment1 = Enrollment(
        enrollment_id="enr_001",
        course_id="crs_001",
        user_id="student-001",
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.WITHDRAWN,
        created_at=datetime.now(timezone.utc),
    )
    conflict_detector._enrollments_db["enr_001"] = enrollment1

    # Add active enrollment
    enrollment2 = Enrollment(
        enrollment_id="enr_002",
        course_id="crs_002",
        user_id="student-001",
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    conflict_detector._enrollments_db["enr_002"] = enrollment2

    # No schedule conflict because first enrollment is withdrawn
    conflicts = conflict_detector.detect_schedule_conflicts("2026ws")

    assert len(conflicts) == 0
