from fastapi.testclient import TestClient
from app.demo import create_demo_app
from evals.public_smoke import verify


def test_public_acceptance_workflow(tmp_path):
    app=create_demo_app(tmp_path/'demo')
    with TestClient(app,base_url='https://testserver') as first:
        # One lifespan owns the sandbox; the second client only owns separate cookies.
        second=TestClient(app,base_url='https://testserver')
        try:
            result=verify(first,second)
            assert result['workflow_passed'] and len(result['checks']) == 5
            assert result['model'] == {'attempted':False}
        finally:
            second.close()
