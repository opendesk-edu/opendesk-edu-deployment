# SPDX-FileCopyrightText: 2024 Zentrum für Digitale Souveränität der öffentlichen Verwaltung (ZenDiS) GmbH
# SPDX-FileCopyrightText: 2024 Bundesministerium des Innern und für Heimat, PG ZenDiS "Projektgruppe für Aufbau ZenDiS"
# SPDX-License-Identifier: Apache-2.0
import pytest
from api.utils.hisinone_client import HISinOneClient, HISinOneClientError


@pytest.mark.asyncio
async def test_hisinone_client_mock_mode():
    """Test HISinOne client in mock mode (no credentials)."""
    client = HISinOneClient()
    assert not client._is_configured()

    async with client as ctx:
        assert ctx is client
        assert ctx._session_cookie == "mock-cookie"


@pytest.mark.asyncio
async def test_hisinone_get_semesters():
    """Test getting semesters from HISinOne (mock mode)."""
    client = HISinOneClient()

    async with client:
        semesters = await client.get_semesters()

        assert isinstance(semesters, list)
        assert len(semesters) > 0
        assert "semester_id" in semesters[0] or "id" in semesters[0]


@pytest.mark.asyncio
async def test_hisinone_get_courses():
    """Test getting courses for a semester (mock mode)."""
    client = HISinOneClient()

    async with client:
        courses = await client.get_courses("2026ws")

        assert isinstance(courses, list)
        assert len(courses) > 0


@pytest.mark.asyncio
async def test_hisinone_get_course_detail():
    """Test getting course details (mock mode)."""
    client = HISinOneClient()

    async with client:
        detail = await client.get_course_detail("LV-001")

        # Mock data returns a list of courses
        assert isinstance(detail, (dict, list))


@pytest.mark.asyncio
async def test_hisinone_get_enrollments():
    """Test getting enrollments for a course (mock mode)."""
    client = HISinOneClient()

    async with client:
        enrollments = await client.get_enrollments("LV-001")

        assert isinstance(enrollments, list)
        assert len(enrollments) > 0


@pytest.mark.asyncio
async def test_hisinone_get_student():
    """Test getting student details (mock mode)."""
    client = HISinOneClient()

    async with client:
        student = await client.get_student("12345")

        assert isinstance(student, dict)
        assert "person_id" in student or "id" in student


def test_hisinone_soap_envelope_builder():
    """Test SOAP envelope construction."""
    client = HISinOneClient()

    # Test simple parameters
    envelope = client._build_soap_envelope(
        method="testMethod",
        params={"param1": "value1", "param2": "value2"},
    )

    assert isinstance(envelope, str)
    assert "testMethod" in envelope
    assert "param1" in envelope
    assert "value1" in envelope
    assert "SOAP-ENV:Envelope" in envelope


def test_hisinone_soap_envelope_builder_list():
    """Test SOAP envelope construction with list parameters."""
    client = HISinOneClient()

    envelope = client._build_soap_envelope(
        method="testMethod",
        params={"items": ["item1", "item2", "item3"]},
    )

    assert isinstance(envelope, str)
    assert "items" in envelope
    assert "item1" in envelope
    assert "item2" in envelope
    assert "item3" in envelope


def test_hisinone_soap_envelope_builder_dict():
    """Test SOAP envelope construction with nested dict parameters."""
    client = HISinOneClient()

    envelope = client._build_soap_envelope(
        method="testMethod",
        params={"nested": {"key1": "value1", "key2": "value2"}},
    )

    assert isinstance(envelope, str)
    assert "nested" in envelope
    assert "key1" in envelope
    assert "value1" in envelope


def test_hisinone_parse_xml_element():
    """Test XML element parsing."""
    from xml.etree import ElementTree as ET

    client = HISinOneClient()

    # Create a simple XML element
    xml_str = """
    <root>
        <child1>value1</child1>
        <child2>value2</child2>
    </root>
    """
    element = ET.fromstring(xml_str)

    result = client._parse_xml_element(element)

    assert isinstance(result, dict)
    assert "root" in result


def test_hisinone_client_error():
    """Test HISinOneClientError exception."""
    error = HISinOneClientError("Test error message")

    assert str(error) == "Test error message"
    assert isinstance(error, Exception)


@pytest.mark.asyncio
async def test_hisinone_client_not_initialized():
    """Test error when client is not initialized (configured mode)."""
    client = HISinOneClient(
        base_url="http://test.com", username="test", password="test"
    )

    with pytest.raises(HISinOneClientError) as exc_info:
        # Try to authenticate without entering async context manager
        await client._authenticate()

    assert "not initialized" in str(exc_info.value)


@pytest.mark.asyncio
async def test_hisinone_get_mock_data():
    """Test mock data generation for different endpoints."""
    client = HISinOneClient()

    # Test semester endpoint
    semester_data = client._get_mock_data("getSemester")
    assert isinstance(semester_data, list)
    assert len(semester_data) > 0

    # Test courses endpoint
    course_data = client._get_mock_data("getLehrveranstaltungen")
    assert isinstance(course_data, list)
    assert len(course_data) > 0

    # Test enrollments endpoint
    enrollment_data = client._get_mock_data("getTeilnehmer")
    assert isinstance(enrollment_data, list)
    assert len(enrollment_data) > 0

    # Test student endpoint
    student_data = client._get_mock_data("getPersonenInfo")
    assert isinstance(student_data, dict)
