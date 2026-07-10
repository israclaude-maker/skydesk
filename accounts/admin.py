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