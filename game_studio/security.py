from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .domain import digest
from .models import AuthThrottle

class ResponseHeaders:
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        response=self.get_response(request)
        response.setdefault('Cache-Control','no-store')
        response['X-Content-Type-Options']='nosniff'
        response['Referrer-Policy']='same-origin'
        response['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        response['X-Frame-Options']='SAMEORIGIN' if request.path.startswith('/studio/preview/') else 'DENY'
        response['Content-Security-Policy']=("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; worker-src 'self' blob:; "
            "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-src 'self'; frame-ancestors "
            +("'self'" if request.path.startswith('/studio/preview/') else "'none'"))
        return response

@transaction.atomic
def throttle(key,limit=10,seconds=300):
    now=timezone.now()
    row,_=AuthThrottle.objects.get_or_create(key=digest(key),defaults={'window_started':now})
    row=AuthThrottle.objects.select_for_update().get(pk=row.pk)
    if row.window_started+timedelta(seconds=seconds)<=now: row.count=0;row.window_started=now
    row.count+=1;row.save()
    return row.count<=limit
