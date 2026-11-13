"""Alembic environment. Every entry point (``alembic`` CLI, ``python -m alembic``,
``command.upgrade``/``downgrade``/``stamp``, offline ``--sql``) goes through the guard:

* schema-changing commands need an authorization: from ``python -m app.guard apply``,
  ``-x nextup_token=stdin`` with the token from guard plan on standard input (same path:
  lock, revalidate, ledger). A token given as an argument is refused (NXG-A10). No
  environment variable or flag bypasses this;
* every other command runs inside a READ ONLY transaction;
* offline SQL needs NEXTUP_ALEMBIC_OFFLINE_REVIEW=1 and never connects.
"""

from alembic import context

from app import guard
from app.models import Base

guard.run_alembic(context, Base.metadata)
