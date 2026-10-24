"""DMZ relay: CardDAV for phones and the push endpoint for Kartei. Nothing else (no admin, no listing pages)."""
from django.urls import path, re_path

from relay import views

urlpatterns = [
    path(".well-known/carddav", views.well_known),
    re_path(r"^carddav/kontakte/(?P<uid>[0-9a-f-]{36})\.vcf$", views.carddav),
    re_path(r"^carddav/(?:kontakte/)?$", views.carddav),
    path("push", views.push),
]
handler404 = views.not_found
handler500 = views.server_error
