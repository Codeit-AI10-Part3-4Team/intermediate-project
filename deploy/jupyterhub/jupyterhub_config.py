# Configuration file for jupyterhub.

c = get_config()  #noqa

c.JupyterHub.bind_url = "http://:8000"

# 로그인 → 바로 JupyterLab
c.Spawner.default_url = "/lab"

# 허용 계정 등록 (리눅스 계정)
c.LocalAuthenticator.create_system_users = False
# ---- 유저 허용 설정 ----
c.Authenticator.allowed_users = {'seen', 'jcpark1010', 'heewon', 'wldn0517', 'yubin'}
c.Authenticator.admin_users = {'seen', 'jcpark1010'}

# ---- 환경변수 설정 ----
c.Spawner.environment = {
    "OPENAI_API_KEY": "키를 입력하세요",
}

c.Spawner.env_keep = [
    'PATH',
    'PYTHONPATH',
    'CONDA_ROOT',
    'CONDA_DEFAULT_ENV',
    'VIRTUAL_ENV',
    'LANG',
    'LC_ALL',
    'JUPYTERHUB_SINGLEUSER_APP',
    'OPENAI_API_KEY',
]
