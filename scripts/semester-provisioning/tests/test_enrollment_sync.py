# SPDX-FileCopyrightText: 2024 Zentrum für Digitale Souveränität der öffentlichen Verwaltung (ZenDiS) GmbH
# SPDX-FileCopyrightText: 2024 Bundesministerium des Innern und für Heimat, PG ZenDiS "Projektgruppe für Aufbau ZenDiS"
# SPDX-License-Identifier: Apache-2.0
"""
Tests for enrollment synchronization engine.
Tests für die Einschreibungssynchronisierungsmaschine.
"""

import pytest
from datetime import datetime, timezone

from api.utils.enrollment_sync import EnrollmentSyncEngine, SyncResult
from api.models.enrollment import Enrollment, EnrollmentStatus, EnrollmentRole
from api.models.course import Course, CourseStatus, LMSPlatform


@pytest.fixture
def sync_engine(mock_course_data):
    """Create an enrollment sync engine with test databases."""
    courses_db = {}
    enrollments_db = {}

    # Add test course
    course = Course(
        course_id=mock_course_data["course_id"],
        lms_course_id=mock_course_data["lms_course_id"],
        semester_id=mock_course_data["semester_id"],
        title=mock_course_data["title"],
        course_code=mock_course_data["course_code"],
        instructor_ids=mock_course_data["instructor_ids"],
        expected_enrollment=mock_course_data["expected_enrollment"],
        lms=LMSPlatform.ILIAS,
        category=mock_course_data["category"],
        status=CourseStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    courses_db[course.course_id] = course

    return EnrollmentSyncEngine(courses_db, enrollments_db)


@pytest.mark.asyncio
async def test_sync_adds_new_enrollments(sync_engine, mock_course_data):
    """Test that sync adds new enrollments from campus management."""
    campus_enrollments = [
        {"student_id": "user-001", "role": "student"},
        {"student_id": "user-002", "role": "student"},
    ]

    # Sync enrollments (dry_run=True so we can check result)
    result = await sync_engine._sync_course_enrollments(
        mock_course_data["course_id"], campus_enrollments, "marvin", dry_run=True
    )

    assert result == (2, 0)  # 2 added, 0 withdrawn


@pytest.mark.asyncio
async def test_sync_withdraws_removed_enrollments(
    sync_engine, mock_enrollment_data, mock_course_data
):
    """Test that sync withdraws enrollments not in campus management."""
    # Add existing enrollment to database
    enrollment = Enrollment(
        enrollment_id=mock_enrollment_data["enrollment_id"],
        course_id=mock_enrollment_data["course_id"],
        user_id=mock_enrollment_data["user_id"],
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    sync_engine._enrollments_db[mock_enrollment_data["enrollment_id"]] = enrollment

    # Campus returns empty enrollment list
    campus_enrollments = []

    # Sync enrollments
    result = await sync_engine._sync_course_enrollments(
        mock_course_data["course_id"], campus_enrollments, "marvin", dry_run=False
    )

    assert result == (0, 1)  # 0 added, 1 withdrawn

    # Check that enrollment was marked as withdrawn
    assert enrollment.status == EnrollmentStatus.WITHDRAWN
    assert enrollment.updated_at is not None


@pytest.mark.asyncio
async def test_sync_skips_duplicate_enrollments(
    sync_engine, mock_enrollment_data, mock_course_data
):
    """Test that sync skips enrollments that already exist."""
    # Add existing enrollment to database
    enrollment = Enrollment(
        enrollment_id=mock_enrollment_data["enrollment_id"],
        course_id=mock_enrollment_data["course_id"],
        user_id=mock_enrollment_data["user_id"],
        role=EnrollmentRole.STUDENT,
        status=EnrollmentStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    sync_engine._enrollments_db[mock_enrollment_data["enrollment_id"]] = enrollment

    # Campus returns same enrollment
    campus_enrollments = [
        {"student_id": mock_enrollment_data["user_id"], "role": "student"}
    ]

    # Sync enrollments
    result = await sync_engine._sync_course_enrollments(
        mock_course_data["course_id"], campus_enrollments, "marvin", dry_run=True
    )

    assert result == (0, 0)  # 0 added, 0 withdrawn


@pytest.mark.asyncio
async def test_sync_with_invalid_source(sync_engine, mock_course_data):
    """Test that sync rejects invalid source."""
    result = await sync_engine.sync_enrollments(
        mock_course_data["semester_id"], source="invalid"
    )

    assert result.semester_id == mock_course_data["semester_id"]
    assert result.source == "invalid"
    assert len(result.errors) > 0
    assert "Invalid source" in result.errors[0]


@pytest.mark.asyncio
async def test_dry_run_does_not_persist_changes(sync_engine, mock_course_data):
    """Test that dry_run mode does not persist changes to database."""
    campus_enrollments = [
        {"student_id": "user-001", "role": "student"},
    ]

    # Sync with dry_run=True
    result = await sync_engine._sync_course_enrollments(
        mock_course_data["course_id"], campus_enrollments, "marvin", dry_run=True
    )

    assert result == (1, 0)  # 1 added in dry run

    # Check that database is still empty
    assert len(sync_engine._enrollments_db) == 0
