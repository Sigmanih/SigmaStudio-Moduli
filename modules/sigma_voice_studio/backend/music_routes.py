"""API di AudioStudio: preset, coda durevole e anteprime musicali."""
from . import music


def handle_music_status(self):
    self.send_json_response({'success': True, 'presets': list(music.PRESETS), **music.status()})


def handle_music_jobs(self):
    self.send_json_response({'success': True, 'jobs': music.music_service().list()})


def handle_music_generate(self):
    try:
        job = music.music_service().submit(self.read_json_body())
        self.send_json_response({'success': True, 'job': job})
    except (ValueError, RuntimeError) as exc:
        self.send_json_response({'success': False, 'error': str(exc)}, 400)


def handle_music_action(self):
    try:
        data = self.read_json_body()
        if not isinstance(data, dict) or not isinstance(data.get('job_id'), str):
            raise ValueError('Indica il lavoro musicale')
        service = music.music_service()
        if data.get('action') == 'resume':
            result = {'job': service.resume(data['job_id'])}
        elif data.get('action') == 'cancel':
            if not service.cancel(data['job_id']):
                raise ValueError('Il lavoro non può essere annullato in questo stato')
            result = {}
        else:
            raise ValueError('Azione non supportata')
        self.send_json_response({'success': True, **result})
    except (ValueError, RuntimeError) as exc:
        self.send_json_response({'success': False, 'error': str(exc)}, 400)
