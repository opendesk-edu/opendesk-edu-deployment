# User Provisioning & Deprovisioning

## Overview

This guide covers automated user lifecycle management for openDesk Edu, including account creation, role assignment, and secure removal using LDAP federation and Keycloak admin APIs.

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   HISinOne   │    │  University  │    │   Keycloak   │    │  openDesk    │
│              │    │  LDAP/AD     │    │              │    │   Edu Apps   │
│              │    │              │    │              │    │              │
│  SOAP API    │───►│  User        │───►│  LDAP Fed.   │───►│  ILIAS       │
│  Events      │    │  Store       │    │  + Admin API │    │  Moodle      │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

## Prerequisites

### Required Tools

- Python 3.12+
- Keycloak Admin CLI (`kcadm`)
- Access to university LDAP/Active Directory
- Keycloak admin credentials
- (Optional) HISinOne API access

### Setup

```bash
# Clone the provisioning tool
cd scripts/user_import

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env
```

## Configuration

### Environment Variables

Create `.env` in `scripts/user_import/`:

```bash
# Keycloak Configuration
KEYCLOAK_URL=https://yourdomain.de/auth
KEYCLOAK_REALM=opendesk
KEYCLOAK_ADMIN_USERNAME=admin
KEYCLOAK_ADMIN_PASSWORD=your-admin-password

# LDAP Configuration
LDAP_SERVER=ldap://ldap.yourinstitution.de
LDAP_BASE_DN=dc=institution,dc=de
LDAP_BIND_DN=cn=admin,dc=institution,dc=de
LDAP_BIND_PASSWORD=ldap-bind-password

# User Mapping
LDAP_USER_SEARCH_BASE=ou=users,dc=institution,dc=de
LDAP_USER_OBJECT_CLASS=inetOrgPerson
LDAP_USERNAME_ATTR=uid
LDAP_EMAIL_ATTR=mail
LDAP_FIRST_NAME_ATTR=givenName
LDAP_LAST_NAME_ATTR=sn

# HISinOne Configuration (Optional)
HISINONE_URL=https://hisinone.yourinstitution.de/qisserver/services2
HISINONE_API_KEY=your-hisinone-api-key

# Provisioning Options
DRY_RUN=true
LOG_LEVEL=INFO
```

## User Provisioning

### Automatic LDAP User Sync

```bash
cd scripts/user_import

# Sync all users from LDAP
python sync_users.py --source ldap --auto-sync

# Sync only active students
python sync_users.py --source ldap --filter "(eduPersonAffiliation=student)"

# Dry run to see what would happen
python sync_users.py --source ldap --dry-run
```

### HISinOne Event-Based Provisioning

```bash
# Listen for HISinOne events and provision users
python hisinone_listener.py

# Process a specific event
python hisinone_listener.py --event immatrikulation --student-id 123456
```

### Manual User Creation

```bash
# Create a single user
python create_user.py \
  --username john.doe \
  --email john.doe@institution.de \
  --first-name "John" \
  --last-name "Doe" \
  --affiliation student \
  --roles "student"
```

## Role Assignment

### Role Mapping Configuration

Define role mappings in `config/roles.json`:

```json
{
  "roles": {
    "student": {
      "description": "Student access",
      "roles": ["student"],
      "groups": ["students"],
      "affiliation": "student",
      "services": ["ilias", "moodle", "bbb", "files"]
    },
    "employee": {
      "description": "Employee access",
      "roles": ["employee"],
      "groups": ["staff"],
      "affiliation": "employee",
      "services": ["email", "groupware", "files", "wiki"]
    },
    "faculty": {
      "description": "Faculty access",
      "roles": ["faculty", "employee"],
      "groups": ["faculty", "staff"],
      "affiliation": "faculty",
      "services": ["ilias", "moodle", "bbb", "email", "groupware", "wiki"]
    },
    "lecturer": {
      "description": "Lecturer access",
      "roles": ["lecturer", "employee"],
      "groups": ["lecturers", "staff"],
      "affiliation": "faculty",
      "services": ["ilias", "moodle", "bbb", "recording", "grades"]
    }
  },
  "mappings": {
    "student": "student",
    "employee": "employee",
    "faculty": "faculty",
    "staff": "employee",
    "prof": "faculty",
    "dozent": "lecturer"
  }
}
```

### Assign Roles

```bash
# Assign role based on LDAP affiliation
python sync_users.py --source ldap --auto-assign-roles

# Manually assign specific roles
python assign_roles.py \
  --username john.doe \
  --roles "student,ilias_user"

# Assign faculty-specific roles
python assign_roles.py \
  --username jane.smith \
  --roles "faculty,lecturer,ilias_instructor"
```

## User Deprovisioning

### Two-Phase Deprovisioning

Phase 1 (Disable):
```bash
# Disable user access (grace period)
python deprovision_user.py \
  --username john.doe \
  --phase disable \
  --grace-period-days 180

# Disable all students who haven't re-registered
python deprovision_user.py \
  --filter "(eduPersonAffiliation=student)" \
  --phase disable \
  --no-ruckmeldung-since 2026-01-15
```

Phase 2 (Permanent Delete):
```bash
# Permanent delete after grace period
python deprovision_user.py \
  --username john.doe \
  --phase delete

# Batch delete users in grace period expired
python deprovision_user.py \
  --phase delete \
  --grace-expired-before 2025-04-06
```

### Bulk Operations

```bash
# Deprovision a batch of students
python deprovision_user.py \
  --phase disable \
  --input-file students-to-archive.csv

# Delete users permanently (after confirmation)
python deprovision_user.py \
  --phase delete \
  --input-file users-to-delete.csv \
  --confirm
```

## SAML Account Linking

When using SAML federation (DFN-AAI), link SAML identities to existing Keycloak users:

```bash
# Link SAML identity to existing user
python link_saml.py \
  --username john.doe \
  --saml-idp "DFN-AAI" \
  --saml-name-id "john.doe@institution.de"

# Bulk link SAML identities for all users
python link_saml.py \
  --source ldap \
  --saml-idp "DFN-AAI"
```

## Scheduling Automated Sync

### Systemd Timer

Create `/etc/systemd/system/opendesk-user-sync.service`:

```ini
[Unit]
Description=openDesk Edu User Sync
After=network.target

[Service]
Type=simple
User=opendesk
WorkingDirectory=/opt/opendesk-edu/scripts/user_import
ExecStart=/usr/bin/python3 sync_users.py --source ldap --auto-sync
Environment=PYTHONUNBUFFERED=1
Restart=always
```

Create `/etc/systemd/system/opendesk-user-sync.timer`:

```ini
[Unit]
Description=openDesk Edu User Sync Timer

[Timer]
OnBootSec=10min
OnUnitActiveSec=1h

[Install]
WantedBy=timers.target
```

```bash
# Enable and start
sudo systemctl enable opendesk-user-sync.timer
sudo systemctl start opendesk-user-sync.timer

# Check status
sudo systemctl status opendesk-user-sync.timer
```

### Cron Job

```bash
# Add to crontab
crontab -e

# Run every hour
0 * * * * /opt/opendesk-edu/scripts/user_import/sync_users.py --source ldap --auto-sync >> /var/log/opendesk-user-sync.log 2>&1
```

## Monitoring & Logging

### Log Files

- `/var/log/opendesk-user-sync.log` - Main sync log
- `/var/log/opendesk-user-provisioning.log` - Provisioning events
- `/var/log/opendesk-user-deprovisioning.log` - Deprovisioning events

### Monitoring Dashboard

```bash
# View recent sync activity
python monitor_sync.py --last-hours 24

# Check failed syncs
python monitor_sync.py --failed-only

# Sync statistics
python monitor_sync.py --stats
```

## Troubleshooting

### LDAP Connection Issues

```bash
# Test LDAP connectivity
python test_ldap.py

# Check LDAP bind
python test_ldap.py --bind

# Test user search
python test_ldap.py --search "(uid=john.doe)"
```

### Keycloak Admin API Issues

```bash
# Test Keycloak connection
python test_keycloak.py

# Check admin credentials
python test_keycloak.py --list-users

# Test role assignment
python test_keycloak.py --test-role-assignment
```

### Sync Failures

```bash
# Run sync with verbose logging
python sync_users.py --source ldap --debug

# Check for errors in logs
tail -f /var/log/opendesk-user-sync.log

# Validate user data before sync
python validate_users.py --input-file users.csv
```

## Security Considerations

### Credentials

- Store all credentials in environment variables, not in code
- Use Keycloak service accounts for automation
- Rotate admin credentials regularly
- Use least privilege principle

### Logging

- Log all provisioning/deprovisioning actions
- Mask sensitive data in logs (passwords, tokens)
- Retain logs for audit purposes (90+ days)
- Monitor for unauthorized access attempts

### Data Protection

- Follow GDPR for personal data
- Implement data minimization
- Provide user consent for data processing
- Allow users to request data export/deletion

## Maintenance

### Regular Tasks

1. **Weekly**: Review sync logs for errors
2. **Monthly**: Check LDAP attribute changes
3. **Quarterly**: Review role mappings
4. **Annually**: Audit user accounts, clean up inactive users

### Backup & Restore

```bash
# Export Keycloak users
python export_users.py --output-keycloak-users.json

# Export user mappings
python export_mappings.py --output-mappings.json

# Restore from backup
python import_users.py --input-keycloak-users.json
```

## Documentation

- [Keycloak Admin Guide](https://www.keycloak.org/docs/latest/server_admin/)
- [LDAP Federation](https://www.keycloak.org/docs/latest/server_admin/index.html#_user-stored-federation)
- [HISinOne API](https://www.his.de/fileadmin/user_upload/his/media/services/technologie/Dokumentation/WebServices/WS_Dokumentation.pdf)

## Support

For provisioning-specific issues, open an issue on GitHub.