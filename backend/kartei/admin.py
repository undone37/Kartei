from django.contrib import admin

from .models import AuditEntry, ExportProfile, FieldDef, Profile, Record, Settings

for m in (Record, FieldDef, ExportProfile, Profile, Settings):
    admin.site.register(m)


@admin.register(AuditEntry)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("at", "username", "action", "target_type", "target_label")
    list_filter = ("action", "target_type")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
