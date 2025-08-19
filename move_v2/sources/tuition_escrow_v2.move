module TuitionEscrow::tuition_escrow_v2 {
	use std::signer;
	use std::error;

	use 0x1::coin;
	use 0x1::aptos_coin::AptosCoin;
	use 0x1::timestamp;
	use aptos_std::table::{Self, Table};

	const E_ALREADY_INITIALIZED: u64 = 1;
	const E_NOT_INITIALIZED: u64 = 2;
	const E_NOT_PAYER: u64 = 3;
	const E_ALL_PAID: u64 = 4;

	struct Agreement has store {
		id: u64,
		payer: address,
		installment_amount: u64,
		total_installments: u64,
		paid_installments: u64,
		start_time_secs: u64,
		interval_secs: u64,
		penalty_bps: u64, // basis points, 10000 = 100%
		grace_period_secs: u64,
		total_paid: u64,
	}

	struct AgreementSummary has copy, drop, store {
		id: u64,
		payer: address,
		installment_amount: u64,
		total_installments: u64,
		paid_installments: u64,
		start_time_secs: u64,
		interval_secs: u64,
		penalty_bps: u64,
		grace_period_secs: u64,
		total_paid: u64,
	}

	struct Store has key {
		agreements: Table<u64, Agreement>,
		next_id: u64,
	}

	fun init_module(admin: &signer) {
		let addr = signer::address_of(admin);
		assert!(addr == @TuitionEscrow, error::permission_denied(E_NOT_INITIALIZED));
		assert!(!exists<Store>(@TuitionEscrow), E_ALREADY_INITIALIZED);
		move_to(admin, Store { agreements: table::new<u64, Agreement>(), next_id: 0 });
	}

	public entry fun create_agreement(
		payer_signer: &signer,
		installment_amount: u64,
		total_installments: u64,
		start_time_secs: u64,
		interval_secs: u64,
		penalty_bps: u64,
		grace_period_secs: u64
	) acquires Store {
		let store = borrow_global_mut<Store>(@TuitionEscrow);
		let id = store.next_id;
		store.next_id = id + 1;
		let agreement = Agreement {
			id,
			payer: signer::address_of(payer_signer),
			installment_amount,
			total_installments,
			paid_installments: 0,
			start_time_secs,
			interval_secs,
			penalty_bps,
			grace_period_secs,
			total_paid: 0,
		};
		table::add(&mut store.agreements, id, agreement);
	}

	public entry fun pay_next_installment(payer_signer: &signer, agreement_id: u64) acquires Store {
		let store = borrow_global_mut<Store>(@TuitionEscrow);
		let agreement_ref = table::borrow_mut(&mut store.agreements, agreement_id);
		let payer_addr = signer::address_of(payer_signer);
		assert!(agreement_ref.payer == payer_addr, E_NOT_PAYER);
		assert!(agreement_ref.paid_installments < agreement_ref.total_installments, E_ALL_PAID);

		let installment_index = agreement_ref.paid_installments; // 0-based
		let due_time = agreement_ref.start_time_secs + agreement_ref.interval_secs * installment_index;
		let now = timestamp::now_seconds();
		let penalty = if (now > due_time + agreement_ref.grace_period_secs) {
			// penalty = amount * bps / 10000
			agreement_ref.installment_amount * agreement_ref.penalty_bps / 10000
		} else {
			0
		};
		let total_due = agreement_ref.installment_amount + penalty;

		let coins = coin::withdraw<AptosCoin>(payer_signer, total_due);
		coin::deposit<AptosCoin>(payer_addr, coins);

		agreement_ref.paid_installments = installment_index + 1;
		agreement_ref.total_paid = agreement_ref.total_paid + total_due;
	}

	#[view]
	public fun get_next_id(): u64 acquires Store {
		let store = borrow_global<Store>(@TuitionEscrow);
		store.next_id
	}

	#[view]
	public fun get_agreement_summary(agreement_id: u64): AgreementSummary acquires Store {
		let store = borrow_global<Store>(@TuitionEscrow);
		let a = table::borrow(&store.agreements, agreement_id);
		AgreementSummary {
			id: a.id,
			payer: a.payer,
			installment_amount: a.installment_amount,
			total_installments: a.total_installments,
			paid_installments: a.paid_installments,
			start_time_secs: a.start_time_secs,
			interval_secs: a.interval_secs,
			penalty_bps: a.penalty_bps,
			grace_period_secs: a.grace_period_secs,
			total_paid: a.total_paid,
		}
	}
}