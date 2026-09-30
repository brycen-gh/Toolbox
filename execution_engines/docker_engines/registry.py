"""Explicit registry of service recipes and deployment handlers."""
from copy import deepcopy
from functools import partial

from . import ctfd, etherpad, home, nextcloud, open_project, portainer, zulip


DEPLOYMENTS = {
    "deploy_home": home,
    "deploy_open_project": open_project,
    "deploy_etherpad": etherpad,
    "deploy_nextcloud": nextcloud,
    "deploy_ctfd": ctfd,
    "deploy_portainer": portainer,
    "deploy_zulip": zulip,
}


# Bind each registered service's deployment handler to the execution engine.
def deployment_actions(engine):
    return {action_id: partial(module.deploy, engine)
            for action_id, module in DEPLOYMENTS.items()}


# Copy a service recipe before resolving variables or applying action overrides.
def deployment_parameters(action_id, overrides=None):
    module = DEPLOYMENTS.get(action_id)
    parameters = deepcopy(module.PARAMETERS) if module else {}
    parameters.update(deepcopy(overrides or {}))
    return parameters
