from django.db import migrations


SITES = [
    ("7b0b0e6c-cf30-4d30-94bb-1e60b8323a01", "Bonny Island Terminal", "Onshore · Niger Delta"),
    ("7b0b0e6c-cf30-4d30-94bb-1e60b8323a02", "Bonga FPSO", "Offshore · Gulf of Guinea"),
    ("7b0b0e6c-cf30-4d30-94bb-1e60b8323a03", "OML 29", "Onshore · Rivers State"),
    ("7b0b0e6c-cf30-4d30-94bb-1e60b8323a04", "Port Harcourt Refinery", "Onshore · Rivers State"),
]

EMPLOYEES = [
    ("8c0b0e6c-cf30-4d30-94bb-1e60b8323a01", "Amina Okafor", "HSE Officer"),
    ("8c0b0e6c-cf30-4d30-94bb-1e60b8323a02", "Tunde Eze", "Field Technician"),
    ("8c0b0e6c-cf30-4d30-94bb-1e60b8323a03", "Grace Nwosu", "Drilling Engineer"),
]


def seed_catalog(apps, schema_editor):
    Site = apps.get_model("reports", "Site")
    Employee = apps.get_model("reports", "Employee")
    Site.objects.using(schema_editor.connection.alias).bulk_create([
        Site(site_id=site_id, facility_name=name, region=region)
        for site_id, name, region in SITES
    ])
    Employee.objects.using(schema_editor.connection.alias).bulk_create([
        Employee(employee_id=employee_id, full_name=name, role=role)
        for employee_id, name, role in EMPLOYEES
    ])


class Migration(migrations.Migration):
    dependencies = [("reports", "0001_initial")]

    operations = [migrations.RunPython(seed_catalog, migrations.RunPython.noop)]
