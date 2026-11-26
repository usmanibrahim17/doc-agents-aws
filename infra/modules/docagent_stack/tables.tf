# DynamoDB, on demand. Items carry `expires_at` (epoch seconds) for the 7-day retention; the
# vendors table is reference data and does not expire.

resource "aws_dynamodb_table" "documents" {
  name         = "${var.name_prefix}-documents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "doc_id"
  tags         = var.tags

  attribute {
    name = "doc_id"
    type = "S"
  }
  attribute {
    name = "session_id"
    type = "S"
  }
  attribute {
    name = "created_at"
    type = "S"
  }
  attribute {
    name = "dup_key"
    type = "S"
  }

  # A visitor's documents, newest first.
  global_secondary_index {
    name            = "by-session"
    projection_type = "ALL"

    key_schema {
      attribute_name = "session_id"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
  }

  # Duplicate detection: hash of session + vendor + invoice number + total.
  global_secondary_index {
    name            = "by-dup-key"
    projection_type = "KEYS_ONLY"

    key_schema {
      attribute_name = "dup_key"
      key_type       = "HASH"
    }
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "audit" {
  name         = "${var.name_prefix}-audit"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "doc_id"
  range_key    = "sk"
  tags         = var.tags

  attribute {
    name = "doc_id"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

# Pending human reviews. Holds the Step Functions task token, which never leaves the server.
resource "aws_dynamodb_table" "reviews" {
  name         = "${var.name_prefix}-reviews"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "doc_id"
  tags         = var.tags

  attribute {
    name = "doc_id"
    type = "S"
  }
  attribute {
    name = "session_id"
    type = "S"
  }

  global_secondary_index {
    name            = "by-session"
    projection_type = "ALL"

    key_schema {
      attribute_name = "session_id"
      key_type       = "HASH"
    }
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "vendors" {
  name         = "${var.name_prefix}-vendors"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "vendor_key"
  tags         = var.tags

  attribute {
    name = "vendor_key"
    type = "S"
  }
}

resource "aws_dynamodb_table_item" "vendor" {
  for_each = { for v in jsondecode(file(var.vendors_file)) : v.key => v }

  table_name = aws_dynamodb_table.vendors.name
  hash_key   = aws_dynamodb_table.vendors.hash_key

  item = jsonencode({
    vendor_key = { S = each.value.key }
    name       = { S = each.value.name }
    category   = { S = each.value.category }
  })
}
