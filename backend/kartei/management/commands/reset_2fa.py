from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from kartei import audit
from kartei.api import profile_of


class Command(BaseCommand):
    help = ("Switch off a user's two-factor sign-in (authenticator lost and no recovery codes left), e.g. the only "
            "admin. The user signs in with the password and sets up 2FA again (at once if it is required).")

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, username, **opts):
        u = User.objects.filter(username__iexact=username).first()
        if not u:
            raise CommandError(f"no user {username!r}")
        p = profile_of(u)
        if not p.totp_secret_enc:
            self.stdout.write(f"{u.username} has no two-factor sign-in")
            return
        p.totp_secret, p.totp_last_counter, p.totp_recovery = "", None, []
        p.totp_failures, p.totp_failed_at = 0, None
        p.save()
        audit.log(None, "update", "user", u.id, u.username, {"totp": [True, False]}, username="system (reset_2fa)")
        self.stdout.write(f"two-factor sign-in of {u.username} switched off; it can be set up again after signing in")
