# Django Local Library

Tutorial "Local Library" website written in Django.

For detailed information about this project see the associated [MDN tutorial home page](https://developer.mozilla.org/en-US/docs/Learn/Server-side/Django/Tutorial_local_library_website).

## Overview

This web application creates an online catalog for a small local library, where users can browse available books and manage their accounts.

The main features that have currently been implemented are:

* There are models for books, book copies, genre, language and authors.
* Users can view list and detail information for books and authors.
* Admin users can create and manage models. The admin has been optimised (the basic registration is present in admin.py, but commented out).
* Librarians can renew reserved books.

![Local Library Model](https://raw.githubusercontent.com/mdn/django-locallibrary-tutorial/master/catalog/static/images/local_library_model_uml.png)


## Quick Start

To get this project up and running locally on your computer:
1. Set up the [Python development environment](https://developer.mozilla.org/en-US/docs/Learn/Server-side/Django/development_environment).
   We recommend using a Python virtual environment.
   > **Note:** This has been tested against Django 3.10 (and may not work or be "optimal" for other versions).
1. Assuming you have Python setup, run the following commands (if you're on Windows you may use `py` or `py -3` instead of `python` to start Python):
   ```
   pip3 install -r requirements.txt
   python3 manage.py makemigrations
   python3 manage.py migrate
   python3 manage.py collectstatic
   python3 manage.py test # Run the standard tests. These should all pass.
   python3 manage.py createsuperuser # Create a superuser
   python3 manage.py runserver
   ```
1. Open a browser to `http://127.0.0.1:8000/admin/` to open the admin site
1. Create a few test objects of each type.
1. Open tab to `http://127.0.0.1:8000` to see the main site, with your new objects.

## Sample data

Load a small public-domain catalog (12 books, 25 copies in every loan status) and two dev users:

```
.venv/bin/python manage.py seed_library --yes-dev-data
```

The command is idempotent: re-running it adds no rows and re-bases due dates on today. It refuses to run
without `--yes-dev-data` because it creates accounts with known passwords. **Use it only on development
databases.**

| User | Password (default) | Notes |
|---|---|---|
| `librarian` | `library-dev-only` | has `can_mark_returned` |
| `member` | `library-dev-only` | plain user, owns several loans |

Use `--password <value>` to choose the password for newly created users. Existing users keep their password
unless you also pass `--reset-passwords`.
