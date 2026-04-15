"""CHAN-25: Static site stack — S3 + CloudFront (OAC) + Cognito User Pool."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
)
from constructs import Construct


class StaticSiteStack(cdk.Stack):
    """Operator portal static hosting with Cognito authentication."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------ #
        # S3 Bucket — private, static website hosting                        #
        # ------------------------------------------------------------------ #
        self.site_bucket = s3.Bucket(
            self,
            "OperatorUiBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            auto_delete_objects=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            website_index_document="index.html",
        )

        # ------------------------------------------------------------------ #
        # CloudFront Distribution — OAC to S3                                #
        # ------------------------------------------------------------------ #
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(
            self.site_bucket,
            origin_access_levels=[
                cloudfront.AccessLevel.READ,
                cloudfront.AccessLevel.LIST,
            ],
        )

        self.distribution = cloudfront.Distribution(
            self,
            "OperatorUiDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=cdk.Duration.seconds(0),
                ),
            ],
        )

        # ------------------------------------------------------------------ #
        # Cognito User Pool — operator authentication                        #
        # ------------------------------------------------------------------ #
        self.user_pool = cognito.UserPool(
            self,
            "OperatorUserPool",
            user_pool_name="ChangeSafe-Operators",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_uppercase=True,
                require_lowercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        self.user_pool_client = self.user_pool.add_client(
            "OperatorUiClient",
            user_pool_client_name="ChangeSafe-OperatorUI",
            auth_flows=cognito.AuthFlow(user_password=True),
        )

        # ------------------------------------------------------------------ #
        # Outputs                                                            #
        # ------------------------------------------------------------------ #
        cdk.CfnOutput(self, "SiteBucketName", value=self.site_bucket.bucket_name)
        cdk.CfnOutput(
            self,
            "DistributionUrl",
            value=self.distribution.distribution_domain_name,
        )
        cdk.CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
        )
