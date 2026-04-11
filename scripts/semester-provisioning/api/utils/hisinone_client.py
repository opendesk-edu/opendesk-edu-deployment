# SPDX-FileCopyrightText: 2024 Zentrum für Digitale Souveränität der öffentlichen Verwaltung (ZenDiS) GmbH
# SPDX-FileCopyrightText: 2024 Bundesministerium des Innern und für Heimat, PG ZenDiS "Projektgruppe für Aufbau ZenDiS"
# SPDX-License-Identifier: Apache-2.0
from typing import Any, Optional
import httpx
from api.config.settings import get_settings
import logging

logger = logging.getLogger(__name__)


class HISinOneClientError(Exception):
    """Exception raised for HISinOne API errors."""

    pass


class HISinOneClient:
    """HISinOne SOAP API client.

    Implements HISinOne SOAP API with Basic authentication.
    Falls back to mock data when no API URL/credentials are configured.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        soap_endpoint: Optional[str] = None,
    ):
        """Initialize HISinOne client with credentials."""
        settings = get_settings()
        self.base_url = base_url or settings.hisinone_api_url
        self.username = username or settings.hisinone_username
        self.password = password or settings.hisinone_password
        self.soap_endpoint = soap_endpoint or settings.hisinone_soap_endpoint
        self._client: Optional[httpx.AsyncClient] = None
        self._session_cookie: Optional[str] = None

    async def __aenter__(self) -> "HISinOneClient":
        """Initialize HTTP client and authenticate."""
        url = self.base_url if self.base_url else "http://localhost"
        self._client = httpx.AsyncClient(base_url=url, timeout=30.0)
        await self._authenticate()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()

    def _is_configured(self) -> bool:
        """Check if API credentials are configured."""
        return bool(self.base_url and self.username and self.password)

    async def _authenticate(self) -> None:
        """Authenticate with HISinOne SOAP API and store session cookie."""
        if not self._is_configured():
            logger.warning(
                "HISinOne API URL and credentials not configured, using mock mode"
            )
            self._session_cookie = "mock-cookie"
            return

        if not self._client:
            raise HISinOneClientError(
                "Client not initialized. Use async context manager."
            )

        # Build SOAP login envelope
        soap_envelope = self._build_soap_envelope(
            method="login",
            params={"username": self.username, "password": self.password},
        )

        try:
            response = await self._client.post(
                self.soap_endpoint,
                content=soap_envelope.encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=utf-8"},
            )
            response.raise_for_status()

            # Extract session cookie from response
            cookies = response.cookies
            if "JSESSIONID" in cookies:
                self._session_cookie = cookies["JSESSIONID"]
                logger.info("Successfully authenticated with HISinOne SOAP API")
            else:
                raise HISinOneClientError("No session cookie returned from HISinOne")

        except httpx.HTTPStatusError as e:
            raise HISinOneClientError(f"HISinOne authentication failed: {e}")

    def _build_soap_envelope(self, method: str, params: dict[str, Any]) -> str:
        """Build SOAP envelope for HISinOne API call.

        Args:
            method: SOAP method name
            params: Method parameters

        Returns:
            SOAP envelope as XML string
        """
        # Build parameter XML
        params_xml = ""
        for key, value in params.items():
            if isinstance(value, (list, dict)):
                # Handle complex types
                if isinstance(value, list):
                    for item in value:
                        params_xml += f"<{key}>{item}</{key}>"
                else:
                    params_xml += f"<{key}>"
                    for subkey, subvalue in value.items():
                        params_xml += f"<{subkey}>{subvalue}</{subkey}>"
                    params_xml += f"</{key}>"
            else:
                params_xml += f"<{key}>{value}</{key}>"

        soap_envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"
                   xmlns:ns1="http://hisinone.de/soap">
    <SOAP-ENV:Body>
        <ns1:{method}>
            {params_xml}
        </ns1:{method}>
    </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

        return soap_envelope

    async def _soap_call(self, method: str, params: dict[str, Any]) -> Any:
        """Make a SOAP call to HISinOne API.

        Args:
            method: SOAP method name
            params: Method parameters

        Returns:
            Parsed response data

        Raises:
            HISinOneClientError: If API call fails
        """
        if not self._is_configured():
            logger.info("HISinOne API not configured, returning mock data")
            return self._get_mock_data(method)

        if not self._client:
            raise HISinOneClientError(
                "Client not initialized. Use async context manager."
            )

        soap_envelope = self._build_soap_envelope(method, params)

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{method}"',
        }

        # Add session cookie if available
        cookies = {}
        if self._session_cookie:
            cookies["JSESSIONID"] = self._session_cookie

        try:
            response = await self._client.post(
                self.soap_endpoint,
                content=soap_envelope.encode("utf-8"),
                headers=headers,
                cookies=cookies,
            )
            response.raise_for_status()

            # Parse SOAP response
            return self._parse_soap_response(response.text)

        except httpx.HTTPStatusError as e:
            # Session expired? Re-authenticate and retry once
            if e.response.status_code == 401:
                logger.info("HISinOne session expired, re-authenticating...")
                await self._authenticate()
                if self._session_cookie:
                    cookies["JSESSIONID"] = self._session_cookie
                response = await self._client.post(
                    self.soap_endpoint,
                    content=soap_envelope.encode("utf-8"),
                    headers=headers,
                    cookies=cookies,
                )
                response.raise_for_status()
                return self._parse_soap_response(response.text)
            raise HISinOneClientError(f"SOAP call failed: {e}")

    def _parse_soap_response(self, xml_response: str) -> Any:
        """Parse SOAP XML response and extract data.

        Args:
            xml_response: Raw XML response string

        Returns:
            Parsed data (dict, list, or primitive)
        """
        # Simple XML parser for HISinOne responses
        # In production, you'd use xml.etree.ElementTree or lxml
        try:
            import xml.etree.ElementTree as ET

            root = ET.fromstring(xml_response)

            # Find the response element
            # HISinOne typically returns data in <return> or methodResponse elements
            namespaces = {
                "soap": "http://schemas.xmlsoap.org/soap/envelope/",
                "ns1": "http://hisinone.de/soap",
            }

            # Get Body content
            body = root.find(".//soap:Body", namespaces)
            if body is None:
                body = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Body")

            if body is not None:
                # Get first child element (the response)
                response_elem = next(iter(body), None)
                if response_elem is not None:
                    return self._parse_xml_element(response_elem)

            # Fallback: return entire response as dict
            return {"raw": xml_response}

        except Exception as e:
            logger.warning(f"Failed to parse SOAP response: {e}")
            return {"raw": xml_response, "parse_error": str(e)}

    def _parse_xml_element(self, element: Any) -> Any:
        """Recursively parse XML element to Python data structure.

        Args:
            element: XML element

        Returns:
            Parsed data (dict, list, or string)
        """
        # Remove namespace from tag
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        # If element has no children, return text content
        if not list(element):
            return element.text or ""

        # Parse children
        result = {}
        for child in element:
            child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            child_value = self._parse_xml_element(child)

            # Handle multiple elements with same tag (convert to list)
            if child_tag in result:
                if not isinstance(result[child_tag], list):
                    result[child_tag] = [result[child_tag]]
                result[child_tag].append(child_value)
            else:
                result[child_tag] = child_value

        return {tag: result}

    async def get_courses(self, semester_code: str) -> list[dict]:
        """Get courses for a semester from HISinOne.

        Args:
            semester_code: Semester identifier (e.g., "2026ws")

        Returns:
            List of course dictionaries
        """
        return await self._soap_call(
            "getLehrveranstaltungen", {"semester": semester_code}
        )

    async def get_course_detail(self, course_id: str) -> dict:
        """Get full course details including times and rooms.

        Args:
            course_id: Course identifier

        Returns:
            Course detail dictionary
        """
        return await self._soap_call("getLehrveranstaltungDetails", {"id": course_id})

    async def get_enrollments(self, course_id: str) -> list[dict]:
        """Get enrolled students for a course.

        Args:
            course_id: Course identifier

        Returns:
            List of enrollment dictionaries
        """
        return await self._soap_call("getTeilnehmer", {"veranstaltung_id": course_id})

    async def get_student(self, student_id: str) -> dict:
        """Get student attributes from HISinOne.

        Args:
            student_id: Student identifier

        Returns:
            Student dictionary with attributes
        """
        return await self._soap_call("getPersonenInfo", {"person_id": student_id})

    async def get_semesters(self) -> list[dict]:
        """List available semesters from HISinOne.

        Returns:
            List of semester dictionaries
        """
        return await self._soap_call("getSemester", {})

    def _get_mock_data(self, endpoint: str) -> Any:
        """Return mock data for development/testing.

        Args:
            endpoint: API endpoint or method name

        Returns:
            Mock response data
        """
        # Normalize endpoint name for matching
        endpoint_lower = endpoint.lower()

        if "semester" in endpoint_lower:
            return [
                {
                    "semester_id": "20261",
                    "name": "Wintersemester 2026/27",
                    "start_date": "2026-10-01",
                    "end_date": "2027-03-31",
                },
                {
                    "semester_id": "20262",
                    "name": "Sommersemester 2027",
                    "start_date": "2027-04-01",
                    "end_date": "2027-09-30",
                },
            ]

        elif "lehrveranstaltung" in endpoint_lower:
            # Course list or detail
            return [
                {
                    "id": "LV-001",
                    "course_code": "INF-101",
                    "title": "Einführung in die Informatik",
                    "title_en": "Introduction to Computer Science",
                    "semester": "2026ws",
                    "instructor_ids": ["prof-001", "prof-002"],
                    "expected_enrollment": 150,
                    "lms": "ilias",
                },
                {
                    "id": "LV-002",
                    "course_code": "MAT-101",
                    "title": "Mathematik I",
                    "title_en": "Mathematics I",
                    "semester": "2026ws",
                    "instructor_ids": ["prof-003"],
                    "expected_enrollment": 200,
                    "lms": "moodle",
                },
            ]

        elif "teilnehmer" in endpoint_lower:
            # Enrollments
            return [
                {
                    "enrollment_id": "ENR-001",
                    "student_id": "student-001",
                    "person_id": "12345",
                    "role": "student",
                    "matriculation_number": "S1234567",
                },
                {
                    "enrollment_id": "ENR-002",
                    "student_id": "student-002",
                    "person_id": "23456",
                    "role": "student",
                    "matriculation_number": "S2345678",
                },
            ]

        elif "person" in endpoint_lower:
            # Student details
            return {
                "person_id": "12345",
                "first_name": "Max",
                "last_name": "Mustermann",
                "email": "max.mustermann@university.de",
                "matriculation_number": "S1234567",
                "program": "Informatik B.Sc.",
                "semester": 1,
                "faculty": "Technische Fakultät",
            }

        # Default empty response
        return []
