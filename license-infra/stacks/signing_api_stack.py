"""CHAN-26: Signing API stack — API Gateway + Lambda + Secrets Manager."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    aws_apigateway as apigw,
    aws_cognito as cognito,
    aws_lambda as lambda_,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class SigningApiStack(cdk.Stack):
    """License signing API backed by Lambda + Secrets Manager."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        user_pool: cognito.IUserPool,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------ #
        # Secrets Manager — Ed25519 private key placeholder                  #
        # ------------------------------------------------------------------ #
        self.signing_key_secret = secretsmanager.Secret(
            self,
            "LicenseSigningKey",
            secret_name="changesafe/license-signing-key",
            description="Ed25519 private key (PEM) for license JWT signing",
            secret_string_value=cdk.SecretValue.unsafe_plain_text(""),
        )

        # ------------------------------------------------------------------ #
        # Lambda Function — sign_license handler                             #
        # ------------------------------------------------------------------ #
        self.sign_function = lambda_.Function(
            self,
            "SignLicenseFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambda/sign_license"),
            memory_size=256,
            timeout=cdk.Duration.seconds(30),
            environment={
                "SIGNING_KEY_SECRET_ARN": self.signing_key_secret.secret_arn,
                "ISSUER": "flentas-license-authority",
            },
        )

        self.signing_key_secret.grant_read(self.sign_function)

        # ------------------------------------------------------------------ #
        # API Gateway REST API                                               #
        # ------------------------------------------------------------------ #
        self.api = apigw.RestApi(
            self,
            "SigningApi",
            rest_api_name="ChangeSafe-License-Signing-API",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=["POST", "OPTIONS"],
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        cognito_authorizer = apigw.CognitoUserPoolsAuthorizer(
            self,
            "CognitoAuthorizer",
            cognito_user_pools=[user_pool],
        )

        sign_resource = self.api.root.add_resource("sign")
        sign_resource.add_method(
            "POST",
            apigw.LambdaIntegration(self.sign_function),
            authorizer=cognito_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # ------------------------------------------------------------------ #
        # Outputs                                                            #
        # ------------------------------------------------------------------ #
        cdk.CfnOutput(self, "SigningApiUrl", value=self.api.url)
        cdk.CfnOutput(
            self,
            "SigningKeySecretArn",
            value=self.signing_key_secret.secret_arn,
        )
