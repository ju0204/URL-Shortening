output "bucket_name" {
  value = aws_s3_bucket.site.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.site.arn
}

output "distribution_id" {
  value = aws_cloudfront_distribution.cdn.id
}

output "distribution_arn" {
  value = aws_cloudfront_distribution.cdn.arn
}

output "cloudfront_domain" {
  value = aws_cloudfront_distribution.cdn.domain_name
}