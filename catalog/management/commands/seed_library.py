import uuid
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Author, Book, BookInstance, Genre, Language

SEED_NAMESPACE = uuid.UUID('6f1c2d1e-52f4-4b8e-9d57-4f0a3a6b7c11')

DEFAULT_PASSWORD = 'library-dev-only'

GENRES = ['Fiction', 'Science Fiction', 'Mystery', "Children's"]
LANGUAGES = ['English', 'French']

# (first, last, born, died)
AUTHORS = [
    ('Jane', 'Austen', date(1775, 12, 16), date(1817, 7, 18)),
    ('Arthur', 'Conan Doyle', date(1859, 5, 22), date(1930, 7, 7)),
    ('Mary', 'Shelley', date(1797, 8, 30), date(1851, 2, 1)),
    ('H. G.', 'Wells', date(1866, 9, 21), date(1946, 8, 13)),
    ('Lewis', 'Carroll', date(1832, 1, 27), date(1898, 1, 14)),
    ('Jules', 'Verne', date(1828, 2, 8), date(1905, 3, 24)),
]

# (isbn, title, (first, last), genres, language, copies, summary)
BOOKS = [
    ('9780000000011', 'Pride and Prejudice', ('Jane', 'Austen'), ['Fiction'], 'English', 3,
     'Elizabeth Bennet navigates manners, marriage and misjudgement in Regency England.'),
    ('9780000000028', 'Emma', ('Jane', 'Austen'), ['Fiction'], 'English', 2,
     'A young matchmaker learns that she understands other hearts better than her own.'),
    ('9780000000035', 'The Hound of the Baskervilles', ('Arthur', 'Conan Doyle'), ['Mystery'], 'English', 3,
     'Sherlock Holmes investigates a spectral hound haunting the Baskerville family.'),
    ('9780000000042', 'A Study in Scarlet', ('Arthur', 'Conan Doyle'), ['Mystery'], 'English', 2,
     'The first meeting of Holmes and Watson, and a murder in a Brixton house.'),
    ('9780000000059', 'Frankenstein', ('Mary', 'Shelley'), ['Fiction', 'Science Fiction'], 'English', 2,
     'A scientist creates life and then refuses to take responsibility for it.'),
    ('9780000000066', 'The Time Machine', ('H. G.', 'Wells'), ['Science Fiction'], 'English', 2,
     'An inventor travels to the year 802,701 and finds a divided humanity.'),
    ('9780000000073', 'The War of the Worlds', ('H. G.', 'Wells'), ['Science Fiction'], 'English', 3,
     'Martians land in Surrey and the Victorian world is not ready.'),
    ('9780000000080', 'The Invisible Man', ('H. G.', 'Wells'), ['Science Fiction'], 'English', 1,
     'A scientist discovers invisibility and loses his grip on everything else.'),
    ('9780000000097', "Alice's Adventures in Wonderland", ('Lewis', 'Carroll'), ["Children's", 'Fiction'], 'English', 2,
     'Alice follows a white rabbit down a hole into a world of logical nonsense.'),
    ('9780000000103', 'Through the Looking-Glass', ('Lewis', 'Carroll'), ["Children's"], 'English', 1,
     'Alice steps through a mirror into a chess-board country.'),
    ('9780000000110', 'Vingt mille lieues sous les mers', ('Jules', 'Verne'), ['Science Fiction'], 'French', 2,
     'Le professeur Aronnax poursuit un monstre marin et découvre le Nautilus.'),
    ('9780000000127', 'Le Tour du monde en quatre-vingts jours', ('Jules', 'Verne'), ['Fiction'], 'French', 2,
     "Phileas Fogg parie qu'il peut faire le tour du monde en quatre-vingts jours."),
]

# Plan by copy position across the whole list: (status, days until due, borrower).
# Negative days means overdue. Positions not listed are available.
LOAN_PLAN = {
    0: ('o', 7, 'member'),
    3: ('o', -5, 'member'),
    6: ('o', 3, 'librarian'),
    9: ('o', 12, 'member'),
    12: ('o', -2, 'librarian'),
    4: ('d', None, None),
    14: ('d', None, None),
    7: ('r', None, None),
    17: ('r', None, None),
}


class Command(BaseCommand):
    help = (
        'Load sample library data (authors, books, copies) and two dev users: '
        '"librarian" and "member". Safe to re-run. Requires --yes-dev-data.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes-dev-data', action='store_true',
            help='Confirm that you want known-password dev users and sample data in this database.')
        parser.add_argument(
            '--password', default=DEFAULT_PASSWORD,
            help='Password for newly created dev users (default: %(default)s).')
        parser.add_argument(
            '--reset-passwords', action='store_true',
            help='Also reset the password of the dev users if they already exist.')

    def handle(self, *args, **options):
        if not options['yes_dev_data']:
            raise CommandError(
                'Refusing to seed: this creates users with known passwords. '
                'Re-run with --yes-dev-data to confirm this is a development database.')

        with transaction.atomic():
            users = self._seed_users(options['password'], options['reset_passwords'])
            books = self._seed_catalog()
            self._seed_copies(books, users)

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {Book.objects.count()} books and {BookInstance.objects.count()} copies. '
            'Users: librarian, member.'))

    def _seed_users(self, password, reset):
        User = get_user_model()
        perm = Permission.objects.get(codename='can_mark_returned')
        users = {}
        for username in ('librarian', 'member'):
            user, created = User.objects.get_or_create(username=username)
            if created or reset:
                user.set_password(password)
                user.save()
            if username == 'librarian':
                user.user_permissions.add(perm)
            users[username] = user
        return users

    def _seed_catalog(self):
        genres = {n: Genre.objects.get_or_create(name=n)[0] for n in GENRES}
        languages = {n: Language.objects.get_or_create(name=n)[0] for n in LANGUAGES}
        authors = {}
        for first, last, born, died in AUTHORS:
            authors[(first, last)], _ = Author.objects.update_or_create(
                first_name=first, last_name=last,
                defaults={'date_of_birth': born, 'date_of_death': died})
        books = []
        for isbn, title, author, book_genres, language, copies, summary in BOOKS:
            book, _ = Book.objects.update_or_create(
                isbn=isbn,
                defaults={'title': title, 'author': authors[author],
                          'summary': summary, 'language': languages[language]})
            book.genre.set([genres[g] for g in book_genres])
            books.append((book, copies))
        return books

    def _seed_copies(self, books, users):
        today = date.today()
        position = 0
        for book, copies in books:
            for n in range(copies):
                status, days, who = LOAN_PLAN.get(position, ('a', None, None))
                position += 1
                BookInstance.objects.update_or_create(
                    id=uuid.uuid5(SEED_NAMESPACE, f'{book.isbn}-{n}'),
                    defaults={
                        'book': book,
                        'imprint': 'Public Domain Reprints, 2020',
                        'status': status,
                        'due_back': today + timedelta(days=days) if days is not None else None,
                        'borrower': users[who] if who else None,
                    })
