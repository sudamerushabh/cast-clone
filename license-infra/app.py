#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.static_site_stack import StaticSiteStack
from stacks.signing_api_stack import SigningApiStack

app = cdk.App()

site = StaticSiteStack(app, "ChangeSafe-StaticSite")
api = SigningApiStack(app, "ChangeSafe-SigningApi", user_pool=site.user_pool)

app.synth()
