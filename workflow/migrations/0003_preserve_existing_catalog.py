from django.db import migrations


def preserve(apps, schema_editor):
    Robot = apps.get_model('workflow', 'Robot')
    Equipment = apps.get_model('workflow', 'Equipment')
    Product = apps.get_model('core', 'Product')
    for equipment in Equipment.objects.all().iterator():
        revision = equipment.revisions.order_by('-id').first()
        if not revision:
            continue
        key = revision.evidence.get('card', {}).get('model_key') or 'equipment-' + str(equipment.pk)
        # Do not silently merge supplier-specific legacy identities.
        if Robot.objects.filter(key=key).exists():
            key = 'equipment-' + str(equipment.pk)
        data = equipment.published.data if equipment.published_id else revision.data
        Robot.objects.create(key=key, equipment=equipment, name=data.get('model', key),
            manufacturer=data.get('manufacturer') or '', general={'legacy_revision_id': revision.pk})
    for product in Product.objects.all().iterator():
        Robot.objects.get_or_create(key='legacy-' + str(product.pk), defaults={
            'legacy_product': product, 'name': product.name, 'manufacturer': '',
            'general': {'legacy_product_id': str(product.pk), 'company_role': 'unknown'}})


class Migration(migrations.Migration):
    dependencies = [('workflow', '0002_robot_scenario_source_cleaningspec_warehousespec_and_more')]
    operations = [migrations.RunPython(preserve, migrations.RunPython.noop)]
