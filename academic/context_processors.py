"""Valores configurables que se muestran en el pie de página del sitio."""

from django.conf import settings


def evaluation_footer(request):
    return {
        'STUDENT_NAME': settings.STUDENT_NAME,
        'STUDENT_SECTION': settings.STUDENT_SECTION,
    }