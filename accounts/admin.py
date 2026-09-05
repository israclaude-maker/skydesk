from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'email', 'remote_id', 'is_online', 'is_staff']
    fieldsets = UserAdmin.fieldsets + (
        ('SkyDesk Info', {'fields': ('remote_id', 'is_online')}),
    )


admin.site.register(CustomUser, CustomUserAdmin)


from django.contrib import admin
from .models import ConnectionLog


@admin.register(ConnectionLog)
class ConnectionLogAdmin(admin.ModelAdmin):
    list_display = ("session_id", "requester", "target", "connect_via",
                     "started_at", "ended_at", "duration_seconds", "status")
    list_filter = ("connect_via", "status")
    search_fields = ("session_id", "requester__username", "target__username",
                      "requester__remote_id", "target__remote_id")
    ordering = ("-started_at",)