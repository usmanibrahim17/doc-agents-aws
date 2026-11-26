# Demo website: private S3 bucket served only through CloudFront (Origin Access Control, HTTPS).

locals {
  web_content_types = {
    html = "text/html; charset=utf-8"
    js   = "application/javascript; charset=utf-8"
    css  = "text/css; charset=utf-8"
    json = "application/json"
    pdf  = "application/pdf"
    jpg  = "image/jpeg"
    png  = "image/png"
  }
  # config.js is generated below with the real API address.
  web_files = toset([for f in fileset(var.web_dir, "**") : f if f != "config.js"])

  # The browser uploads to and reads from the uploads bucket with presigned URLs.
  uploads_origins = [
    "https://${aws_s3_bucket.uploads.bucket}.s3.amazonaws.com",
    "https://${aws_s3_bucket.uploads.bucket}.s3.${data.aws_region.current.region}.amazonaws.com",
  ]

  # The API host is a wildcard to avoid a cycle: the API's CORS needs the CloudFront domain.
  web_csp = join("; ", [
    "default-src 'none'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "connect-src 'self' https://*.execute-api.${data.aws_region.current.region}.amazonaws.com ${join(" ", local.uploads_origins)}",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
  ])
}

resource "aws_s3_bucket" "web" {
  bucket        = "${var.name_prefix}-web-${local.account_id}"
  force_destroy = var.force_destroy
  tags          = var.tags
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_object" "web" {
  for_each = local.web_files

  bucket       = aws_s3_bucket.web.id
  key          = each.value
  source       = "${var.web_dir}/${each.value}"
  etag         = filemd5("${var.web_dir}/${each.value}")
  content_type = local.web_content_types[reverse(split(".", each.value))[0]]
  tags         = var.tags
}

resource "aws_s3_object" "web_config" {
  bucket       = aws_s3_bucket.web.id
  key          = "config.js"
  content      = "window.DOCAGENT_API = ${jsonencode(aws_apigatewayv2_api.this.api_endpoint)};\n"
  content_type = local.web_content_types["js"]
  tags         = var.tags
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${var.name_prefix}-web"
  description                       = "CloudFront signs its requests to the private web bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Short TTL so a deploy shows up quickly without needing invalidations.
resource "aws_cloudfront_cache_policy" "web" {
  name        = "${var.name_prefix}-web"
  min_ttl     = 0
  default_ttl = 300
  max_ttl     = 3600

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true

    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

resource "aws_cloudfront_response_headers_policy" "web" {
  name = "${var.name_prefix}-web-security"

  security_headers_config {
    content_security_policy {
      content_security_policy = local.web_csp
      override                = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
  }
}

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  price_class         = "PriceClass_100"
  default_root_object = "index.html"
  comment             = "${var.name_prefix} demo site"
  tags                = var.tags

  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_id                = "web-bucket"
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  default_cache_behavior {
    target_origin_id           = "web-bucket"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.web.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.web.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

data "aws_iam_policy_document" "web_bucket" {
  statement {
    sid       = "AllowCloudFrontRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.web.arn]
    }
  }

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = data.aws_iam_policy_document.web_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.web]
}
