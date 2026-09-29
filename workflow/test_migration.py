from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ExistingCatalogMigrationTests(TransactionTestCase):
    def test_existing_rows_and_published_revision_survive(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old_target = [('workflow', '0001_initial')]
        executor.migrate(old_target)
        try:
            apps = executor.loader.project_state(old_target).apps
            User = apps.get_model('auth', 'User')
            Supplier = apps.get_model('workflow', 'Supplier')
            Equipment = apps.get_model('workflow', 'Equipment')
            Revision = apps.get_model('workflow', 'EquipmentRevision')
            user = User.objects.create(username='migration-user')
            supplier = Supplier.objects.create(name='Original supplier')
            equipment = Equipment.objects.create(supplier=supplier, identity='original')
            revision = Revision.objects.create(equipment=equipment, author=user, state='published',
                data={'model': 'Existing R1', 'manufacturer': 'Existing maker', 'payload_kg': 500},
                evidence={'original': 'must survive'})
            equipment.published = revision; equipment.save()
            executor = MigrationExecutor(connection); executor.migrate(latest)
            from .models import Robot, EquipmentRevision, Equipment as CurrentEquipment
            robot = Robot.objects.get(equipment_id=equipment.pk)
            self.assertEqual(robot.name, 'Existing R1')
            self.assertEqual(CurrentEquipment.objects.get(pk=equipment.pk).published_id, revision.pk)
            self.assertEqual(EquipmentRevision.objects.get(pk=revision.pk).evidence, {'original': 'must survive'})
            self.assertEqual(EquipmentRevision.objects.get(pk=revision.pk).data['payload_kg'], 500)
        finally:
            MigrationExecutor(connection).migrate(latest)
