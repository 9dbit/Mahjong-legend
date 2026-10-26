from django.urls import path, re_path
from game_studio import views as v

urlpatterns=[
    path('health',v.health),path('api/studio/session',v.session),path('api/studio/login',v.sign_in),
    path('api/studio/logout',v.sign_out),path('api/studio/setup',v.setup),path('api/studio/overview',v.overview),
    path('api/studio/drafts',v.drafts),path('api/studio/drafts/<uuid:draft_id>',v.draft_detail),
    path('api/studio/drafts/<uuid:draft_id>/validate',v.draft_validate),
    path('api/studio/drafts/<uuid:draft_id>/publish',v.draft_publish),
    path('api/studio/drafts/<uuid:draft_id>/preview',v.draft_preview),
    path('api/studio/drafts/<uuid:draft_id>/simulate',v.simulate),
    path('api/studio/assets',v.assets),path('api/studio/assets/<uuid:asset_id>/render',v.asset_render),
    path('api/studio/assets/import-baseline',v.import_baseline),
    path('api/studio/assets/<uuid:asset_id>/content',v.asset_content),
    path('api/studio/jobs',v.jobs),path('api/studio/jobs/<uuid:job_id>/cancel',v.job_cancel),
    path('api/studio/releases',v.releases),path('api/studio/releases/<uuid:release_id>/activate',v.release_activate),
    path('media/<uuid:asset_id>/<str:sha>',v.published_media),
    path('api/audio-live',v.live_audio),
    path('api/preview/<str:preview_token>/audio-live',v.live_audio),
    path('studio/preview/<str:token>',v.preview_page),
    re_path(r'^api/preview/(?P<preview_token>[^/]+)/(?P<operation>state|spin|reset|verify|last-round)$',v.public_api),
    re_path(r'^api/(?P<operation>state|spin|reset|verify|last-round|diagnostics/spin)$',v.public_api),
    re_path(r'^(?P<path>.*)$',v.static_page),
]
