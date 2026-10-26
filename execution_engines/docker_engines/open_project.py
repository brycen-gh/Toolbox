"""OpenProject recipe; editable values live in variables/docker_variables/open_project.yaml."""

PARAMETERS = {
    "name": "${OPENPROJECT_CONTAINER_NAME}",
    "image": "${OPENPROJECT_IMAGE}",
    "recreate": "${OPENPROJECT_RECREATE}",
    "restart": "${OPENPROJECT_RESTART_POLICY}",
    "ports": ["${OPENPROJECT_HOST_PORT}:${OPENPROJECT_CONTAINER_PORT}"],
    "volumes": ["${OPENPROJECT_DATA_VOLUME}:${OPENPROJECT_DATA_PATH}"],
    "environment": {
        "SECRET_KEY_BASE": "${OPENPROJECT_SECRET_KEY_BASE}",
        "OPENPROJECT_HOST__NAME": "${OPENPROJECT_HOST_NAME}",
        "OPENPROJECT_HTTPS": "${OPENPROJECT_HTTPS}",
    },
}


# Deploy open project using the resolved service recipe and shared engine.
def deploy(engine, parameters):
    return engine._run_container(parameters)
